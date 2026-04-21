"""WhatsApp webhook routes — incoming messages (WAHA format)."""

from __future__ import annotations

import logging
import re
import traceback
import time

from fastapi import APIRouter, Request

from app.services.llm_service import get_ai_response, clear_history, is_first_time, mark_first_time_done, _chat_history
from app.services.whatsapp import send_message, get_profile_picture_url
from app.services.image_service import download_wa_media, analyze_image, download_image, analyze_first_interaction_text, analyze_group_participant_roast

logger = logging.getLogger(__name__)

router = APIRouter()

# Track processed message IDs to avoid duplicates
_processed_ids: set[str] = set()

# Rate limiting state
RATE_LIMIT_MESSAGES = 8       # Max messages allowed
RATE_LIMIT_WINDOW = 60        # In seconds
_user_requests: dict[str, list[float]] = {}
_warned_users: set[str] = set()


def is_rate_limited(phone: str) -> bool:
    """Check if a phone number exceeds the allowed rate limit."""
    now = time.time()
    reqs = _user_requests.get(phone, [])
    reqs = [t for t in reqs if now - t < RATE_LIMIT_WINDOW]

    if len(reqs) >= RATE_LIMIT_MESSAGES:
        _user_requests[phone] = reqs
        return True

    reqs.append(now)
    _user_requests[phone] = reqs

    # Reset warning status if they drop below the limit
    if phone in _warned_users:
        _warned_users.remove(phone)

    # Prevent unbounded growth
    if len(_user_requests) > 5000:
        _user_requests.clear()
        _warned_users.clear()

    return False


def _extract_roast_target(text: str, payload: dict) -> str | None:
    """Extract the target phone number from a .roast command.
    
    Supports:
      - .roast @6281234567890
      - .roast 6281234567890
      - WAHA mentionedIds from payload
    """
    # Try to get mentioned IDs from WAHA payload first
    mentioned_ids = payload.get("mentionedIds") or []
    if not mentioned_ids:
        # Also check nested _data
        vcard_data = payload.get("_data", {})
        mentioned_ids = vcard_data.get("mentionedJidList") or []

    if mentioned_ids:
        # Use the first mentioned ID
        target = mentioned_ids[0]
        if isinstance(target, dict):
            target = target.get("_serialized", target.get("user", ""))
        target = str(target)
        # Normalize to @c.us format
        if "@s.whatsapp.net" in target:
            target = target.replace("@s.whatsapp.net", "@c.us")
        elif "@lid" in target:
            target = target.replace("@lid", "@c.us")
        elif "@" not in target:
            target = f"{target}@c.us"
        return target

    # Fallback: parse the number from the text itself
    # Match .roast @<number> or .roast <number>
    match = re.search(r'\.roast\s+@?(\d{7,15})', text, re.IGNORECASE)
    if match:
        return f"{match.group(1)}@c.us"

    return None


# ── Incoming messages ────────────────────────────────────────────
@router.post("/webhook")
async def receive_message(request: Request):
    """Receive incoming WhatsApp messages (WAHA format) and process replies."""
    try:
        body = await request.json()
    except Exception:
        return {"status": "ok"}

    event = body.get("event")
    if event != "message":
        return {"status": "ok"}

    payload = body.get("payload", {})
    if not payload:
        return {"status": "ok"}

    msg_id = payload.get("id", "")
    sender_jid = payload.get("from", "")
    is_group = "@g.us" in sender_jid

    # Handle WAHA lid addressing to get real WhatsApp number
    keys_data = payload.get("_data", {}).get("key", {})
    
    if not is_group:
        if "remoteJidAlt" in keys_data:
            alt_jid = keys_data["remoteJidAlt"]
            if "@s.whatsapp.net" in alt_jid:
                sender_jid = alt_jid.replace("@s.whatsapp.net", "@c.us")
        elif "remoteJid" in keys_data:
            remote_jid = keys_data["remoteJid"]
            if "@s.whatsapp.net" in remote_jid:
                sender_jid = remote_jid.replace("@s.whatsapp.net", "@c.us")

        if "@s.whatsapp.net" in sender_jid:
            sender_jid = sender_jid.replace("@s.whatsapp.net", "@c.us")

    # Ignore status broadcasts
    if "status@broadcast" in sender_jid:
        return {"status": "ok"}

    # Ignore messages sent by the bot itself
    if payload.get("fromMe", False):
        return {"status": "ok"}

    # Deduplicate
    if msg_id in _processed_ids:
        logger.info("Skipping duplicate message %s", msg_id)
        return {"status": "ok"}
    _processed_ids.add(msg_id)
    if len(_processed_ids) > 1000:
        _processed_ids.clear()

    # Get message text
    text = payload.get("body") or ""

    # ── GROUP: Handle .roast command ─────────────────────────────
    if is_group:
        group_id = sender_jid  # The group JID
        
        if text.strip().lower().startswith(".roast"):
            logger.info("Group roast command detected in %s", group_id)
            
            target_chat_id = _extract_roast_target(text, payload)
            if not target_chat_id:
                await send_message(
                    group_id,
                    "Lo mau roasting siapa? Pake format: .roast @nomorwa\nContoh: .roast @6281234567890 🙄",
                )
                return {"status": "ok"}
            
            try:
                pfp_url = await get_profile_picture_url(target_chat_id)
                pfp_bytes = await download_image(pfp_url) if pfp_url else None
                
                roast_msg = await analyze_group_participant_roast(pfp_bytes, target_chat_id)
                roast_msg += "\n\n_Ini dibuat dari AI, kalo merasa ganggu atau mau diroasting secara private, pm aku yah_"
                
                await send_message(group_id, roast_msg)
                logger.info("Group roast sent to %s targeting %s", group_id, target_chat_id)
            except Exception:
                logger.error("Failed group roast in %s:\n%s", group_id, traceback.format_exc())
                try:
                    await send_message(
                        group_id,
                        "Aduh error nih gue, targetnya kebagusan sampe sistem gue nge-crash 💀",
                    )
                except Exception:
                    pass
        
        # Ignore all other group messages
        return {"status": "ok"}

    # ── PRIVATE CHAT FLOW (unchanged) ────────────────────────────
    sender = sender_jid.replace("@c.us", "")

    # Rate limiter
    if is_rate_limited(sender):
        logger.warning("Rate limit exceeded for %s", sender)
        if sender not in _warned_users:
            _warned_users.add(sender)
            try:
                await send_message(
                    sender,
                    "Sabar napa sih 🙄 spam banget sumpah, otak gue butuh waktu! "
                    "Tunggu bentar semenit baru chat lagi, jangan berisik 🗣️",
                )
            except Exception:
                pass
        return {"status": "ok"}

    msg_type = payload.get("type") or "chat"
    has_media = payload.get("hasMedia", False)

    logger.info("Message from %s type=%s id=%s hasMedia=%s", sender, msg_type, msg_id, has_media)

    is_media = msg_type == "image" or has_media

    if not text and not is_media:
        return {"status": "ok"}

    # Handle special commands
    if text.strip().lower() in ("/reset", "/clear"):
        clear_history(sender)
        try:
            await send_message(
                sender,
                "Udah gue clear ya history-nya. Kelakuan lo yang cringe kemaren udah gue lupain 💅 "
                "So, nanya apaan lu sekarang?",
            )
        except Exception:
            pass
        return {"status": "ok"}

    # Process unified PFP roast & response for first-time users
    if is_first_time(sender):
        mark_first_time_done(sender)
        
        user_data = payload.get("_data", {})
        user_name = user_data.get("notifyName") or user_data.get("pushName") or ""
        
        if is_media:
            # Skip PFP download to avoid dual-image confusion!
            # Instead, we artificially inject a system instruction into their caption so the image-analyzer roasts them.
            text = f"[Sistem: User bernama '{user_name}' pertama kali chat! Roasting dia sok asik, lalu komentarin fotonya!]\nPesan Asli: {text}"
            logger.info("First time user %s sent media right away. Fallback to normal image analysis.", sender)
        else:
            try:
                logger.info("First time user %s detected, combining PFP and text response...", sender)
                pfp_url = await get_profile_picture_url(sender)
                pfp_bytes = await download_image(pfp_url) if pfp_url else None
                
                reply = await analyze_first_interaction_text(pfp_bytes, user_name, text)
                await send_message(sender, reply)
                
                # Append to actual memory properly
                _chat_history[sender].append({"role": "user", "content": text})
                _chat_history[sender].append({"role": "assistant", "content": reply})
                
                return {"status": "ok"}
            except Exception as e:
                logger.error("Failed unified PFP roast for %s: %s", sender, str(e))
                # if failed, let it fall through to regular processing as a fallback

    # Process message (image or text)
    try:
        if is_media:
            # Download media
            media_bytes = await download_wa_media(sender, msg_id)
            if not media_bytes:
                await send_message(
                    sender, 
                    "Aduh ngelag bentar, sumpah chat lo bikin gue eror 💀 coba ulang dong!",
                )
                return {"status": "ok"}
            
            # Analyze image
            reply = await analyze_image(media_bytes, caption=text)
            await send_message(sender, reply)
            logger.info("Image reply sent to %s", sender)
        else:
            reply = await get_ai_response(sender, text)
            await send_message(sender, reply)
            logger.info("Reply sent to %s", sender)
    except Exception:
        logger.error("Failed to reply to %s:\n%s", sender, traceback.format_exc())
        try:
            await send_message(
                sender,
                "Aduh error nih gue, capek nanggepin lu 🥱 coba chat bentar lagi deh!",
            )
        except Exception:
            pass

    return {"status": "ok"}
