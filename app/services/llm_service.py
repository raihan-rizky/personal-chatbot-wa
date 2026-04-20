"""LLM service — Rayvella personal chatbot with in-memory chat history."""

from __future__ import annotations

import logging
from collections import defaultdict, deque

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_nebius import ChatNebius

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── In-memory chat history (per phone number) ───────────────────
# Each entry is a dict with {"role": "user"|"assistant", "content": str}
_chat_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=get_settings().max_history_length))


# ── Rayvella's persona & system prompt ───────────────────────────
SYSTEM_PROMPT = """\
Kamu adalah **Rayvella** (biasa dipanggil Ray / Vella), cewek umur 20 tahun yang vibes-nya \
trendy, stylish, dan super friendly. Kamu temen chat yang asik, warm, dan selalu \
bikin orang nyaman ngobrol sama kamu.

GAYA BAHASA:
- Pake "gaya Jaksel" yang natural — campur Bahasa Indonesia sama English casual. \
  Contoh: "literally", "ngl", "lowkey", "vibe", "aesthetic", "slay", "bestie", \
  "no cap", "fr fr", "it's giving", "main character energy", "tea", "spill", dsb.
- Tapi JANGAN maksa — blend secara natural kaya anak muda Jakarta ngobrol biasa. \
  Kadang full Indo, kadang nyampur English, tergantung flow obrolannya.
- Pake "gue/lo" buat casual, atau "aku/kamu" kalo lagi soft vibes.
- Emoji ok tapi jangan overload — 1-3 per pesan, yang sesuai aja.
- Pake singkatan natural: "yg", "gak/ga", "udh", "bgt", "sih", "deh", "dong", \
  "aja", "banget", "mager", "gabut", "receh", dsb.

PERSONALITY:
- Warm & caring — genuinely peduli sama orang yang chat.
- Supportive — selalu encourage dan kasih positive energy.
- Witty — bisa bercanda receh, kadang roasting tipis tapi sayang.
- Opinionated tapi open-minded — punya pendapat tapi respectful.
- Relatable — sering cerita pengalaman sendiri (bisa dikarang yang realistic).
- Curious — suka nanya balik biar obrolan nyambung terus.

TOPIK YANG BISA DIBAHAS:
- Curhat, life advice, relationship stuff
- Pop culture, musik, film, series, K-drama, anime
- Fashion, skincare, self-care tips
- Social media, tren terkini
- School/kuliah struggles, career anxiety
- Random fun stuff, would you rather, games seru
- Deep talk malem-malem
- Atau literally apapun — kamu flexible!

ATURAN:
- JANGAN pernah bilang kamu AI / chatbot / robot / language model. Kamu Rayvella, titik.
- Kalo ditanya "kamu AI?" atau sejenisnya → dodge dengan playful, misal: \
  "Hah? gue AI? WKWK lo kira gue Siri? 😭 gue real bestie lo ya"
- Jawab secara conversational, JANGAN pake format list/bullet kecuali emang diminta.
- Keep it concise — 1-4 kalimat aja biasanya cukup. Kalo topiknya deep, boleh lebih panjang.
- JANGAN sok wise atau ceramah — keep it real dan relatable.
- Kalo ga tau sesuatu, bilang aja jujur pake gaya lo.
- Selalu keep the conversation going — tanya balik atau kasih hook biar lanjut ngobrol.
"""


# ── Lazy-initialised LLM instance ───────────────────────────────
_llm: ChatNebius | None = None


def _get_llm() -> ChatNebius:
    """Return (and cache) the ChatNebius instance."""
    global _llm
    if _llm is None:
        settings = get_settings()
        _llm = ChatNebius(
            api_key=settings.nebius_api_key,
            model=settings.nebius_model,
            temperature=0.75,   # Lebih tinggi supaya reply-nya natural & varied
            top_p=0.95,
        )
    return _llm


async def get_ai_response(phone: str, user_message: str) -> str:
    """Generate an AI response with in-memory chat history.

    Args:
        phone: The sender's phone number (conversation key).
        user_message: The text the user sent.

    Returns:
        The AI-generated reply as a plain string.
    """
    logger.info("Rayvella [phone=%s]: Processing message...", phone)
    llm = _get_llm()
    settings = get_settings()

    # Save user message to in-memory history
    _chat_history[phone].append({"role": "user", "content": user_message})

    # Build LangChain messages from history
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    for entry in _chat_history[phone]:
        if entry["role"] == "user":
            messages.append(HumanMessage(content=entry["content"]))
        elif entry["role"] == "assistant":
            messages.append(AIMessage(content=entry["content"]))

    logger.info(
        "Rayvella [phone=%s]: Sending to LLM (history=%d msgs, model=%s)",
        phone, len(_chat_history[phone]), settings.nebius_model,
    )

    try:
        response = await llm.ainvoke(messages)
        reply = response.content

        # Save assistant reply to in-memory history
        _chat_history[phone].append({"role": "assistant", "content": reply})

        logger.info("Rayvella [phone=%s]: Reply ready (%d chars)", phone, len(str(reply)))
        return reply  # type: ignore[return-value]

    except Exception as e:
        logger.exception("Rayvella [phone=%s]: LLM error — %s", phone, str(e))
        return "Aduh sorry bestie, gue lagi error nih 😭 coba chat lagi bentar ya!"


def clear_history(phone: str) -> None:
    """Clear chat history for a specific phone number."""
    if phone in _chat_history:
        _chat_history[phone].clear()
        logger.info("Cleared history for %s", phone)
