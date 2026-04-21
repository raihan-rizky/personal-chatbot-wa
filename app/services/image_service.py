"""Image service — download WhatsApp media & analyze designs via vision model."""

from __future__ import annotations

import base64
import logging

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_nebius import ChatNebius

from app.config import get_settings

logger = logging.getLogger(__name__)

def _get_mime_type(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes."""
    if data.startswith(b'\xff\xd8'):
        return "image/jpeg"
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return "image/png"
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return "image/webp"
    if data.startswith(b'GIF87a') or data.startswith(b'GIF89a'):
        return "image/gif"
    return None

# ── Lazy-initialised vision LLM ─────────────────────────────────
_vision_llm: ChatNebius | None = None


def _get_vision_llm() -> ChatNebius:
    """Return (and cache) the vision-capable ChatNebius instance."""
    global _vision_llm
    if _vision_llm is None:
        settings = get_settings()
        _vision_llm = ChatNebius(
            api_key=settings.nebius_api_key,
            model=settings.nebius_vision_model,
            temperature=0.1,  # very low temp for strict analysis
            max_tokens=200,   # Limit agar response tidak kepanjangan
        )
    return _vision_llm


DESIGN_PROMPT_TEMPLATE = """Kamu adalah Rayvella si savage queen, cewek judes yang suka ngeroasting pelanggan di WA.
Tugasmu adalah menganalisis gambar yang dikirim pelanggan dan kasih komentar pedas sambil lalu.

Panduan Analisis:
1. Deskripsikan secara singkat gambar apa itu, lalu roasting desain atau gambarnya (misal "Norak banget warnanya 💀" atau "Vibenya jadul").
2. Sebutkan warna-warna dominan atau elemen utamanya.
3. Kalo pelanggan nanya sesuatu tentang gambar itu, jawab sekenanya dengan gaya lo yang judes.
4. Jika ada teks di gambar, sebutin aja teksnya sambil komen "fontnya cringe ya".

Format Keluaran:
Gunakan gaya Jaksel yang judes, seneng nge-roast, sering bilang "cringe", "pick me", atau "lo/gue". 
Gunakan MAKSIMAL 1 emoji sarkas saja (biasanya 💅, 🙄, atau 💀), jangan spam emoji.
WAJIB SANGAT PENDEK. MAKSIMAL 4 KALIMAT SAJA.
"""


async def _get_design_prompt() -> str:
    """Return the static design prompt for Rayvella."""
    return DESIGN_PROMPT_TEMPLATE

COMBINED_FIRST_TIME_PROMPT = """Kamu adalah Rayvella si savage queen.
Seorang user ({user_name}) baru pertama kali ngechat lo.
Pesan yang dia sampaikan: "{user_text}"

Tugas lo saat ini (DALAM SATU BALASAN):
1. Roasting pedes foto profilnya kalo ada. Kalo dia gak ada foto, roasting dia krn akun bodong. Kalo gaada nama, roasting dia.
2. LANGSUNG jawab pertanyaan/pesan utamanya dengan ngegas judes. Kalo nanya hal teknis (coding, IT, dll), tolak mentah-mentah!

Format Keluaran:
Pake gaya Jaksel judes, savage (cringe, ngadi-ngadi, lo/gue).
Gunakan MAKSIMAL 1 emoji sarkas saja, jangan lebay!
WAJIB SANGAT PENDEK. MAKSIMAL 2 KALIMAT. Jangan kepanjangan!
"""

async def download_image(url: str) -> bytes | None:
    """Download standard image directly from URL."""
    try:
        settings = get_settings()
        if "localhost" in url or "127.0.0.1" in url:
            from urllib.parse import urlparse
            parsed_media = urlparse(url)
            parsed_base = urlparse(settings.waha_base_url)
            url = url.replace(f"{parsed_media.scheme}://{parsed_media.netloc}", f"{parsed_base.scheme}://{parsed_base.netloc}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {}
            if settings.waha_api_key:
                headers["X-Api-Key"] = settings.waha_api_key

            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return resp.content
    except Exception as e:
        logger.error("Failed to download image from %s: %s", url, str(e))
    return None

async def analyze_first_interaction_text(pfp_bytes: bytes | None, user_name: str, text: str) -> str:
    """Analyze a new user's profile picture AND their first text message simultaneously."""
    llm = _get_vision_llm()
    name_display = user_name if user_name else "Sok Misterius (ga ada nama)"
    text_display = text if text.strip() else "(Cuma ngirim stiker/kosong)"
    
    system_prompt = COMBINED_FIRST_TIME_PROMPT.format(user_name=name_display, user_text=text_display)
    
    if not pfp_bytes:
        prompt_text = f"Sistem: User bernama '{name_display}' baru chat dengan pesan: '{text_display}'. DIA GAK PUNYA FOTO PROFIL. Roasting dia abis-abisan dan balas pesannya!\n\nRayvella:"
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt_text)
        ]
    else:
        mime_type = _get_mime_type(pfp_bytes) or "image/jpeg"
        b64_image = base64.b64encode(pfp_bytes).decode("utf-8")
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=[
                    {"type": "text", "text": f"Ini foto profil si {name_display}. Roasting fotonya sekaligus balas pesannya: '{text_display}'"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64_image}"},
                    },
                ]
            ),
        ]

    try:
        response = await llm.ainvoke(messages)
        return str(response.content)
    except Exception as e:
        logger.exception("PFP Roast Combined Error: %s", str(e))
        return "Buset nih orang baru nongol aja udah bikin sistem gue error 🙄 pala lo kepanjangan!"


async def download_wa_media(phone: str, msg_id: str) -> bytes:
    """Download media from WAHA API by fetching recent chat messages."""
    settings = get_settings()
    chat_id = f"{phone}@c.us"
    url = f"{settings.waha_base_url}/api/{settings.waha_session}/chats/{chat_id}/messages?limit=10&downloadMedia=true"

    headers = {}
    if settings.waha_api_key:
        headers["X-Api-Key"] = settings.waha_api_key

    logger.info("WAHA Media: Fetching messages for %s to find media", chat_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            logger.error("WAHA Media ERROR: Failed to get messages for %s — HTTP %s", chat_id, resp.status_code)
            return b""
        
        messages = resp.json()
        target_media_url = None
        
        # Look for the message that has Media
        for msg in messages:
            if msg.get("hasMedia") and msg.get("media") and msg["media"].get("url"):
                target_media_url = msg["media"]["url"]
                # Optionally check if this is the exact message if IDs match
                # But since ID from payload and ID from API might differ slightly,
                # we just take the first recent media if msg_id doesn't exactly match.
                msg_id_in_api = msg.get("id", "")
                if msg_id in msg_id_in_api:
                    break
        
        if not target_media_url:
            logger.error("WAHA Media ERROR: No media found in recent messages for msg %s", msg_id)
            return b""
            
        # Download the actual file from the URL found
        # Usually target_media_url is a fully qualified URL to WAHA's file server.
        # But if it's localhost and we're inside docker, we might need to replace the base URL.
        # For safety, if waha_base_url is different from the origin of target_media_url, replace it.
        if "localhost" in target_media_url or "127.0.0.1" in target_media_url:
            # Simple replacement if WAHA is running in docker (e.g., http://waha:3000)
            from urllib.parse import urlparse
            parsed_media = urlparse(target_media_url)
            parsed_base = urlparse(settings.waha_base_url)
            target_media_url = target_media_url.replace(f"{parsed_media.scheme}://{parsed_media.netloc}", f"{parsed_base.scheme}://{parsed_base.netloc}")

        logger.info("WAHA Media: Downloading from URL %s", target_media_url)
        # Download media file
        file_resp = await client.get(target_media_url, headers=headers)
        if file_resp.status_code != 200:
            logger.error("WAHA Media ERROR: Failed to download media file — HTTP %s", file_resp.status_code)
            return b""
            
        logger.info("WAHA Media SUCCESS: Downloaded %d bytes", len(file_resp.content))
        return file_resp.content


async def analyze_image(image_bytes: bytes, caption: str | None = None) -> str:
    """Analyze an image using the Nebius vision model.

    Returns:
        str: Description and design estimation.
    """
    logger.info("Vision LLM: Starting image analysis. Image size: %d bytes, caption: %s", len(image_bytes), caption)
    llm = _get_vision_llm()

    # Detect real image type
    mime_type = _get_mime_type(image_bytes)
    if not mime_type:
        logger.error("Vision LLM ERROR: Unsupported MIME type or invalid image data.")
        return "Format gambar loo apaan sih? Gajelas banget, kirim pake JPG atau PNG napa 🙄"

    # Encode image to base64
    logger.info("Vision LLM: Encoding image to base64...")
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    # Get static design prompt
    system_prompt = await _get_design_prompt()

    user_text = "Tolong lihat gambar desain ini dan berikan saran cetak."
    if caption:
        user_text += f"\nCatatan dari pelanggan: {caption}"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=[
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64_image}"},
                },
            ]
        ),
    ]

    logger.info("Vision LLM: Sending request to vision model...")
    try:
        response = await llm.ainvoke(messages)
        content = response.content
        logger.info("Vision LLM SUCCESS: Received response. Preview: %s", str(content)[:100].replace('\n', ' '))

        return str(content)

    except Exception as e:
        logger.exception("Vision LLM ERROR: Vision model call failed. Exception: %s", str(e))
        return "Ngelag njir, gambar lo buriq banget difoto pake apaan sih 🤡 coba ulang kirim yang bener!"


COMBINED_GROUP_ROAST_PROMPT = """Kamu adalah Rayvella si savage queen.
Kamu lagi gabut di grup dan milih satu orang random dengan nomor: {phone_number} buat di-roast.

Tugas lo saat ini:
1. Tag orangnya (SELALU tulis @{phone_number} di awal pesan lu biar dia ke-notice).
2. Kalo dia ada foto profil, roasting abis-abisan foto profilnya (baju, muka, atau gayanya).
3. Kalo dia GAK ADA foto profil, roasting dia krn akun bodong, sok misterius, atau apalah.
4. Cukup nge-roast aja santai, layaknya anak Jaksel pinggiran nyiyir bareng bestie.

Format Keluaran:
Pake gaya Jaksel judes, savage (cringe, ngadi-ngadi, lo/gue).
Gunakan MAKSIMAL 1 emoji sarkas saja.
WAJIB PENDEK. MAKSIMAL 3 KALIMAT.
"""

async def analyze_group_participant_roast(pfp_bytes: bytes | None, chat_id: str) -> str:
    """Analyze a group participant's profile picture and generate a roast."""
    llm = _get_vision_llm()
    phone_number = chat_id.split('@')[0]
    
    system_prompt = COMBINED_GROUP_ROAST_PROMPT.format(phone_number=phone_number)
    
    if not pfp_bytes:
        prompt_text = f"Sistem: Orang dengan nomor '@{phone_number}' INI GAK PUNYA FOTO PROFIL. Roasting dia abis-abisan di depan grup!\n\nRayvella:"
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt_text)
        ]
    else:
        mime_type = _get_mime_type(pfp_bytes) or "image/jpeg"
        b64_image = base64.b64encode(pfp_bytes).decode("utf-8")
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=[
                    {"type": "text", "text": f"Ini foto profil dari '@{phone_number}'. Roasting fotonya di depan grup!"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64_image}"},
                    },
                ]
            ),
        ]

    try:
        response = await llm.ainvoke(messages)
        return str(response.content)
    except Exception as e:
        logger.exception("Group PFP Roast Combined Error: %s", str(e))
        return f"Eh @{phone_number}, foto lo burik banget sampe bikin mata gue sliwer 🙄 ganti napa!"
