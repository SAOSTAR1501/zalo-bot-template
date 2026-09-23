import json
import logging
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Header, Depends
from sqlalchemy.orm import Session

from config.settings import settings
from database.connection import init_db, get_db
from database.models import MessageLog, GroupKnowledge
from services.formatter import clean_markdown_for_zalo
from services.zalo_client import zalo_client
from handlers.message_handler import message_handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("zalo_bot")

# Initialize Database tables
init_db()

app = FastAPI(
    title="Zalo Bot AI Template",
    description="Production-ready Zalo Bot with Multi-LLM, 12h Group Memory and Knowledge Base",
    version="1.0.0"
)


@app.on_event("startup")
async def startup_event():
    """Pre-warm embedding model and persistent connections in background."""
    import threading
    def _warmup():
        try:
            from services.semantic_memory_service import get_embedding_model
            from services.sticker_service import sticker_service
            get_embedding_model()
            zalo_client.get_me()
            # Pre-load and persist sticker catalog so it is available offline.
            sticker_service.list_catalog()
            logger.info("Startup warmup complete: FastEmbed, Zalo Client and Sticker catalog ready.")
        except Exception as e:
            logger.warning(f"Startup warmup note: {e}")
    threading.Thread(target=_warmup, daemon=True).start()



@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "bot_configured": bool(settings.ZALO_BOT_TOKEN),
        "ai_provider": settings.AI_PROVIDER,
        "context_window_hours": settings.MAX_CONTEXT_HOURS
    }


@app.post("/webhook")
async def webhook(
    request: Request,
    secret_token: Optional[str] = Header(None, alias="X-Bot-Api-Secret-Token")
):
    """
    Main webhook receiver for Zalo Bot Platform.
    """
    body = await request.body()
    body_str = body.decode(errors="ignore")

    # Validate secret token if configured
    if settings.ZALO_WEBHOOK_SECRET and secret_token != settings.ZALO_WEBHOOK_SECRET:
        logger.warning(f"Invalid X-Bot-Api-Secret-Token: {secret_token}")
        raise HTTPException(status_code=401, detail="Invalid secret token")

    try:
        data = json.loads(body_str)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON payload: {body_str[:200]}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Process webhook event
    result = message_handler.process_webhook_event(data)
    return result


@app.get("/api/logs")
async def get_logs(limit: int = 20, db: Session = Depends(get_db)):
    """Retrieve recent conversation logs."""
    rows = db.query(MessageLog).order_by(MessageLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "chat_id": r.user_id,
            "message": r.message,
            "reply": r.reply,
            "event_type": r.event_type,
            "created_at": r.created_at.isoformat()
        }
        for r in rows
    ]


@app.get("/api/knowledge")
async def get_knowledge(chat_id: str, db: Session = Depends(get_db)):
    """Retrieve knowledge entries for a specific group/chat."""
    rows = db.query(GroupKnowledge).filter(GroupKnowledge.chat_id == str(chat_id)).all()
    return [
        {
            "id": r.id,
            "topic": r.topic,
            "content": r.content,
            "created_by": r.created_by,
            "is_auto": r.is_auto,
            "created_at": r.created_at.isoformat()
        }
        for r in rows
    ]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True
    )
