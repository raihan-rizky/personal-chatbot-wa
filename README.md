# 💜 Rayvella — Personal WhatsApp Chatbot

A warm, trendy, and friendly personal AI chatbot powered by **Nebius AI Studio** on WhatsApp via **WAHA**.

## ✨ Who is Rayvella?

**Rayvella** (Ray/Vella) is a 20-year-old virtual bestie who speaks in natural **"gaya Jaksel"** — mixing casual Indonesian with English slang. She's:

- 🫶 **Warm & caring** — genuinely cares about you
- 💅 **Trendy & stylish** — up-to-date with pop culture
- 😂 **Witty** — bisa bercanda receh, roasting tipis tapi sayang
- 🧠 **Supportive** — always there for deep talks and life advice
- 🎯 **Relatable** — talks like your actual bestie

## 🏗️ Architecture

```
WhatsApp ←→ WAHA API ←→ FastAPI (Webhook) ←→ Nebius AI Studio (LLM)
```

- **No database** — chat history is kept in-memory (resets on restart)
- **No external fetching** — pure conversational AI, no product catalog
- **Lightweight** — simple and fast

## 🚀 Quick Start

### 1. Clone & install

```bash
git clone <repo-url>
cd personal-chatbot-wa
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run

```bash
# With uvicorn directly
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Or with uv
uv run dev
```

### 4. Set up WAHA webhook

Point your WAHA webhook to: `http://your-server:8000/webhook`

## 📝 Commands

| Command | Description |
|---------|-------------|
| `/reset` or `/clear` | Clear chat history & start fresh |

## 🔧 Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `NEBIUS_API_KEY` | Nebius AI Studio API key | *required* |
| `NEBIUS_MODEL` | LLM model name | `Qwen/Qwen3-14B` |
| `WAHA_BASE_URL` | WAHA server URL | `http://localhost:3000` |
| `WAHA_SESSION` | WAHA session name | `default` |
| `WAHA_API_KEY` | WAHA API key | *(empty)* |

## 📁 Project Structure

```
personal-chatbot-wa/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py             # Settings from .env
│   ├── routes/
│   │   └── webhook.py        # WhatsApp webhook handler
│   └── services/
│       ├── llm_service.py    # Rayvella AI brain + chat history
│       └── whatsapp.py       # Send messages via WAHA
├── .env.example
├── requirements.txt
├── pyproject.toml
└── vercel.json
```

## 🌐 Deploy to Vercel

The project includes `vercel.json` for easy deployment as a serverless function.

> ⚠️ Note: In-memory chat history **won't persist** across serverless invocations. For production, consider adding Redis or a simple DB for history.
