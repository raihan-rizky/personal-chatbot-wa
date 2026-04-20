"""WhatsApp webhook routes — incoming messages (WAHA format)."""

from __future__ import annotations

import logging
import traceback
import time

from fastapi import APIRouter, Request

from app.services.llm_service import get_ai_response, clear_history, is_first_time
from app.services.whatsapp import send_message, get_profile_picture_url
from app.services.image_service import download_wa_media, analyze_image, download_image, analyze_profile_picture

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

    # Handle WAHA lid addressing to get real WhatsApp number
    keys_data = payload.get("_data", {}).get("key", {})
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

    # Ignore group messages and status broadcasts
    if "@g.us" in sender_jid or "status@broadcast" in sender_jid:
        return {"status": "ok"}

    # Ignore messages sent by the bot itself
    if payload.get("fromMe", False):
        return {"status": "ok"}

    sender = sender_jid.replace("@c.us", "")

    # Deduplicate
    if msg_id in _processed_ids:
        logger.info("Skipping duplicate message %s", msg_id)
        return {"status": "ok"}
    _processed_ids.add(msg_id)
    if len(_processed_ids) > 1000:
        _processed_ids.clear()

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

    # Get message text
    text = payload.get("body") or ""
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

    # Process PFP roast for first-time users
    if is_first_time(sender):
        try:
            logger.info("First time user %s detected, fetching PFP for roasting...", sender)
            
            user_data = payload.get("_data", {})
            user_name = user_data.get("notifyName") or user_data.get("pushName") or ""
            
            pfp_url = await get_profile_picture_url(sender)
            pfp_bytes = await download_image(pfp_url) if pfp_url else None
            
            pfp_roast = await analyze_profile_picture(pfp_bytes, user_name)
            await send_message(sender, pfp_roast)
        except Exception as e:
            logger.error("Failed to process first-time PFP roast for %s: %s", sender, str(e))

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
