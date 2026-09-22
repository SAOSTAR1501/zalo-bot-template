import logging
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from config.settings import settings
from database.connection import SessionLocal
from database.models import MessageLog, GroupContextSummary

logger = logging.getLogger(__name__)


class ContextService:
    def get_optimized_context(
        self,
        chat_id: str,
        max_hours: int = settings.MAX_CONTEXT_HOURS,
        recent_count: int = settings.RECENT_MESSAGES_COUNT
    ) -> Tuple[str, List[Dict[str, str]]]:
        """
        Retrieves episodic context:
        1. Rolling condensed summary of older messages.
        2. Last N raw conversation turns within max_hours.
        Saves >80% tokens compared to raw history.
        """
        db = SessionLocal()
        try:
            time_limit = datetime.utcnow() - timedelta(hours=max_hours)
            
            # 1. Fetch rolling summary (if within max_hours)
            summary_row = db.query(GroupContextSummary).filter(
                GroupContextSummary.chat_id == str(chat_id)
            ).first()
            
            rolling_summary = ""
            if summary_row and summary_row.updated_at >= time_limit:
                rolling_summary = summary_row.summary or ""

            # 2. Fetch last N raw messages
            rows = (
                db.query(MessageLog)
                .filter(MessageLog.user_id == str(chat_id))
                .filter(MessageLog.created_at >= time_limit)
                .filter(MessageLog.reply.isnot(None))
                .order_by(MessageLog.id.desc())
                .limit(recent_count)
                .all()
            )
            rows.reverse()

            recent_history = []
            from services.formatter import strip_quota_badges
            for r in rows:
                clean_msg = r.message
                clean_rep = strip_quota_badges(r.reply or "")
                if clean_msg and clean_rep and not clean_rep.startswith("["):
                    recent_history.append({"role": "user", "content": clean_msg})
                    recent_history.append({"role": "assistant", "content": clean_rep})

            return rolling_summary, recent_history

        except Exception as e:
            logger.error(f"Error loading optimized context: {e}")
            return "", []
        finally:
            db.close()

    def get_history(self, chat_id: str, max_hours: int = settings.MAX_CONTEXT_HOURS, limit: int = 10) -> List[Dict[str, str]]:
        """
        Legacy fallback: retrieves recent conversation history.
        """
        _, history = self.get_optimized_context(chat_id, max_hours=max_hours, recent_count=limit)
        return history

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

    def maybe_update_summary(self, chat_id: str):
        """
        Checks if unsummarized messages exceed threshold, and if so,
        updates the rolling episodic summary via LLM in background.
        """
        db = SessionLocal()
        try:
            # 1. Get current summary record
            summary_record = db.query(GroupContextSummary).filter(
                GroupContextSummary.chat_id == str(chat_id)
            ).first()

            last_id = summary_record.last_summarized_id if summary_record else 0
            existing_summary = summary_record.summary if summary_record else ""

            # 2. Query unsummarized messages
            unsummarized = (
                db.query(MessageLog)
                .filter(MessageLog.user_id == str(chat_id))
                .filter(MessageLog.id > last_id)
                .filter(MessageLog.reply.isnot(None))
                .order_by(MessageLog.id.asc())
                .all()
            )

            # Keep RECENT_MESSAGES_COUNT untouched in raw turns
            if len(unsummarized) < (settings.AUTO_SUMMARIZE_THRESHOLD + settings.RECENT_MESSAGES_COUNT):
                return

            # Batch to summarize: all unsummarized except the last RECENT_MESSAGES_COUNT
            to_summarize = unsummarized[:-settings.RECENT_MESSAGES_COUNT]
            if not to_summarize:
                return

            new_max_id = to_summarize[-1].id

            # Format text chunk
            chunk_lines = []
            for m in to_summarize:
                chunk_lines.append(f"User: {m.message}")
                if m.reply:
                    chunk_lines.append(f"Bot: {m.reply[:200]}")
            chunk_text = "\n".join(chunk_lines)

            # 3. Call LLM to produce updated concise summary
            from services.llm_service import llm_service
            new_summary = llm_service.summarize_conversation(existing_summary, chunk_text)
            if not new_summary or new_summary.startswith("["):
                logger.warning(f"Summarization returned error/empty: {new_summary}")
                return

            # 4. Save to DB
            if not summary_record:
                summary_record = GroupContextSummary(
                    chat_id=str(chat_id),
                    summary=new_summary,
                    last_summarized_id=new_max_id,
                    updated_at=datetime.utcnow()
                )
                db.add(summary_record)
            else:
                summary_record.summary = new_summary
                summary_record.last_summarized_id = new_max_id
                summary_record.updated_at = datetime.utcnow()

            db.commit()
            logger.info(f"Updated episodic summary for chat {chat_id} (up to id {new_max_id})")
        except Exception as e:
            logger.error(f"Error updating episodic summary for {chat_id}: {e}")
        finally:
            db.close()

    def trigger_async_summary_update(self, chat_id: str):
        """
        Fires background thread for summary rollup without blocking webhook response.
        """
        t = threading.Thread(target=self.maybe_update_summary, args=(chat_id,), daemon=True)
        t.start()

    def clear_context(self, chat_id: str) -> bool:
        """
        Clears conversation history and summary for a chat/group.
        """
        db = SessionLocal()
        try:
            db.query(MessageLog).filter(MessageLog.user_id == str(chat_id)).delete()
            db.query(GroupContextSummary).filter(GroupContextSummary.chat_id == str(chat_id)).delete()
            db.commit()
            return True
        except Exception as e:
            logger.error(f"Error clearing context: {e}")
            return False
        finally:
            db.close()


context_service = ContextService()

