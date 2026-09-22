import logging
from datetime import datetime, timedelta
from typing import List, Dict
from config.settings import settings
from database.connection import SessionLocal
from database.models import MessageLog

logger = logging.getLogger(__name__)


class ContextService:
    def get_history(self, chat_id: str, max_hours: int = settings.MAX_CONTEXT_HOURS, limit: int = settings.MAX_CONTEXT_TURNS) -> List[Dict[str, str]]:
        """
        Retrieves recent conversation history for a given chat/group within max_hours.
        """
        db = SessionLocal()
        try:
            time_limit = datetime.utcnow() - timedelta(hours=max_hours)
            rows = (
                db.query(MessageLog)
                .filter(MessageLog.user_id == str(chat_id))
                .filter(MessageLog.created_at >= time_limit)
                .filter(MessageLog.reply.isnot(None))
                .order_by(MessageLog.id.desc())
                .limit(limit)
                .all()
            )
            rows.reverse()
            history = []
            for r in rows:
                clean_msg = r.message
                clean_rep = r.reply
                if clean_msg and clean_rep and not clean_rep.startswith("["):
                    history.append({"role": "user", "content": clean_msg})
                    history.append({"role": "assistant", "content": clean_rep})
            return history
        except Exception as e:
            logger.error(f"Error loading conversation context: {e}")
            return []
        finally:
            db.close()

    def save_turn(self, chat_id: str, message: str, reply: str, event_type: str = "message.text.received"):
        """
        Saves a conversation turn into database.
        """
        db = SessionLocal()
        try:
            db.add(MessageLog(
                user_id=str(chat_id),
                message=str(message),
                reply=str(reply),
                event_type=str(event_type)
            ))
            db.commit()
        except Exception as e:
            logger.error(f"Error saving message turn: {e}")
        finally:
            db.close()

    def clear_context(self, chat_id: str) -> bool:
        """
        Clears conversation history for a chat/group.
        """
        db = SessionLocal()
        try:
            db.query(MessageLog).filter(MessageLog.user_id == str(chat_id)).delete()
            db.commit()
            return True
        except Exception as e:
            logger.error(f"Error clearing context: {e}")
            return False
        finally:
            db.close()


context_service = ContextService()
