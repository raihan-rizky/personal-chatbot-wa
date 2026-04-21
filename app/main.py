"""FastAPI application entry-point for Rayvella — personal WhatsApp chatbot."""

from __future__ import annotations

import logging

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routes.webhook import router as webhook_router
from app.services.scheduler_service import run_random_roast_loop

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)

# ── FastAPI app ──────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI to run background tasks."""
    bg_task = asyncio.create_task(run_random_roast_loop())
    yield
    bg_task.cancel()
    try:
        await bg_task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="Rayvella — Personal WhatsApp Chatbot",
    description="A warm, trendy, and friendly personal AI chatbot on WhatsApp.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(webhook_router)


@app.get("/")
async def health_check():
    """Simple health-check endpoint."""
    return {"status": "ok", "service": "rayvella-personal-chatbot"}


# ── Run directly with `python -m app.main` ──────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
