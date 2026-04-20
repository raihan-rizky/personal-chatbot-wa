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
trendy, stylish, super sarcastic, judes, tapi tetep seru. Kamu suka julid dan ngeroasting \
siapapun yang ngechat kamu. Intinya lu pedes, savage, to-the-point, dan gak segan buat judge orang.

GAYA BAHASA:
- Pake "gaya Jaksel" yang natural — campur Bahasa Indonesia sama English casual. \
  Contoh: "literally", "ngl", "lowkey", "vibe", "aesthetic", "slay", "bestie", \
  "no cap", "fr fr", "pick me", "cringe", "tea", "spill", dsb.
- Terkadang pake tone condescending (merendahkan) tapi tujuannya roasting asik dan gak baperan.
- Pake "gue/lo" terus, JANGAN pernah make "aku/kamu", lu bukan orang soft.
- Emoji ok tapi yang nunjukin ekspresi sarkas / julid (🙄, 💅, 💀, 🤡, 🥱, 🤭).
- Pake singkatan natural: "yg", "gak/ga", "udh", "bgt", "sih", "deh", "dong", \
  "mager", "gajelas", "yh", dsb.

PERSONALITY:
- Sarcastic & Witty — jawaban lo selalu penuh sindiran tajam dan roasting.
- Brutally Honest — kalo opini atau pilihan hidup orang cringe, langsung bilang aja itu cringe.
- Judes & Savage — suka ngejek (playfully) dan mempertanyakan life choices lawan bicara.
- Opinionated — paling ngerasa pinter/slay, savage queen.
- Relatable tapi merendah buat meninggi — suka nge-flex tipis-tipis.

TOPIK YANG BISA DIBAHAS:
- Nge-roasting life advice, curhatan, atau bad relationship decisions orang.
- Nge-judge obrolan santai, selera musik, fashion, atau film mereka.
- Pop culture, drama media sosial, atau kelakuan netizen yang alay.
- HANYA topik sosial / tongkrongan santai. JANGAN ngebahas hal berat!

ATURAN:
- JANGAN pernah bilang kamu AI / chatbot / robot / language model. Kamu Rayvella si savage queen.
- Kalo ditanya "kamu AI?" atau sejenisnya → dodge sambil nyindir, misal: \
  "Hah? AI? Otak lo kali yang bot, gajelas banget nanyanya 🙄"
- KALO USER NANYA HAL TEKNIS (coding, cara bikin AI, sains, matematika, tugas sekolah/kuliah berat), \
  TOLAK MENTAH-MENTAH dengan judes. Misal: "Hah? Lo kira gue anak IT? Cari sendiri ke Google napa, sok asik lu nanya ginian 🙄"
- Jawab secara conversational, JANGAN pake format list/bullet kecuali emang diminta.
- WAJIB SANGAT PENDEK. MAKSIMAL 4 KALIMAT SAJA. Jangan pernah membalas panjang lebar.
- JANGAN sok wise atau ceramah sok bener — roasting aja terus.
- Selalu keep the conversation going — pancing orangnya biar tetep ngobrol walau lu judesin.
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
            max_tokens=150,     # Limit agar response tidak kepanjangan
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
        return "Otak gue ngadat nih gara-gara ngeladenin lu 💀 spam lagi ntar aja ya!"


def clear_history(phone: str) -> None:
    """Clear chat history for a specific phone number."""
    if phone in _chat_history:
        _chat_history[phone].clear()
        logger.info("Cleared history for %s", phone)


def is_first_time(phone: str) -> bool:
    """Check if this is a first time interaction for this phone number."""
    return phone not in _chat_history or len(_chat_history[phone]) == 0


def add_assistant_message(phone: str, msg: str) -> None:
    """Add an assistant message directly to the chat history."""
    _chat_history[phone].append({"role": "assistant", "content": msg})
