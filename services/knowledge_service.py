import logging
from datetime import datetime, timedelta
from typing import Optional, List
from config.settings import settings
from database.connection import SessionLocal
from database.models import GroupKnowledge, MessageLog
from services.llm_service import llm_service
from services.formatter import clean_markdown_for_zalo

logger = logging.getLogger(__name__)


class KnowledgeService:
    def save(self, chat_id: str, content: str, created_by: str = "Thành viên", topic: str = "Kiến thức ghi nhớ", is_auto: bool = False) -> bool:
        """
        Saves a piece of knowledge into the long-term knowledge base.
        """
        db = SessionLocal()
        try:
            entry = GroupKnowledge(
                chat_id=str(chat_id),
                content=str(content).strip(),
                topic=str(topic).strip() or "Kiến thức chung",
                created_by=str(created_by) or "Hệ thống",
                is_auto=is_auto
            )
            db.add(entry)
            db.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving knowledge entry: {e}")
            return False
        finally:
            db.close()

    def get_knowledge_summary(self, chat_id: str, limit: int = 5) -> str:
        """
        Retrieves knowledge entries formatted for prompt injection or user display.
        """
        db = SessionLocal()
        try:
            rows = (
                db.query(GroupKnowledge)
                .filter(GroupKnowledge.chat_id == str(chat_id))
                .order_by(GroupKnowledge.id.desc())
                .limit(limit)
                .all()
            )
            if not rows:
                return ""
            items = []
            for r in reversed(rows):
                tag = "Tự động tổng hợp 12h" if r.is_auto else f"Lưu bởi {r.created_by}"
                items.append(f"• [{r.topic} - {tag}]: {r.content}")
            return "\n".join(items)
        except Exception as e:
            logger.error(f"Error fetching group knowledge: {e}")
            return ""
        finally:
            db.close()

    def summarize_and_store(self, chat_id: str, hours: int = settings.MAX_CONTEXT_HOURS) -> str:
        """
        Summarizes discussions within the last N hours and stores into the knowledge base.
        """
        db = SessionLocal()
        try:
            time_limit = datetime.utcnow() - timedelta(hours=hours)
            rows = (
                db.query(MessageLog)
                .filter(MessageLog.user_id == str(chat_id))
                .filter(MessageLog.created_at >= time_limit)
                .order_by(MessageLog.id.asc())
                .all()
            )
            if len(rows) < 2:
                return "Chưa có đủ nội dung thảo luận trong 12 tiếng qua để tổng hợp kiến thức."

            chat_text = "\n".join([f"- {r.message} (Bot: {r.reply or ''})" for r in rows if r.message])
            prompt = (
                f"Dưới đây là các trao đổi trong nhóm trong {hours} giờ qua:\n\n"
                f"{chat_text}\n\n"
                "Hãy tóm tắt ngắn gọn các kiến thức quan trọng, quyết định, phân công việc hoặc nội dung cốt lõi của cuộc thảo luận này thành các gạch đầu dòng ngắn gọn (bằng tiếng Việt, tuyệt đối không dùng ** hay #)."
            )

            raw_summary = llm_service.generate_reply(prompt)
            clean_sum = clean_markdown_for_zalo(raw_summary)

            self.save(
                chat_id=chat_id,
                content=clean_sum,
                created_by="Hệ thống Tóm tắt 12h",
                topic=f"Tổng hợp {datetime.now().strftime('%d/%m %H:%M')}",
                is_auto=True
            )
            return clean_sum
        except Exception as e:
            logger.error(f"Error summarizing group discussion: {e}")
            return f"Lỗi khi tổng hợp: {e}"
        finally:
            db.close()


knowledge_service = KnowledgeService()
