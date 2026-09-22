import re
from typing import Optional, Tuple
from config.settings import settings
from services.context_service import context_service
from services.knowledge_service import knowledge_service


class CommandHandler:
    @staticmethod
    def get_menu_text() -> str:
        return (
            "📋 MENU CHỨC NĂNG CỦA BOT:\n\n"
            "1️⃣ /save <nội dung> : Lưu kiến thức quan trọng vào kho nhóm\n"
            "2️⃣ /knowledge : Xem kho kiến thức đã lưu trữ\n"
            "3️⃣ /summary : Tóm tắt nội dung thảo luận 12 giờ qua\n"
            "4️⃣ /clear : Xóa lịch sử trò chuyện ngắn hạn gần đây\n"
            "5️⃣ /help : Xem lại menu hướng dẫn này\n\n"
            "👉 Mẹo: Bạn có thể gõ nhanh phím số 2, 3, 4 hoặc đặt câu hỏi bất kỳ để bot giải đáp!"
        )

    def handle_command(self, cleaned_text: str, chat_id: str, user_id: str, sender_name: str) -> Tuple[bool, Optional[str]]:
        """
        Returns (is_command, reply_text).
        If is_command is False, message should be dispatched to LLM.
        """
        text_lower = cleaned_text.lower().strip()

        # 1. Start / Hello
        if text_lower in ["/start", "/hello", "hello", "hi", "xin chào", "chào"]:
            name_str = f" {sender_name}" if sender_name else ""
            reply = f"Xin chào{name_str}! Mình là Bot Sao Assistant.\n\n" + self.get_menu_text()
            return True, reply

        # 2. Menu / Help / Phím 5
        if text_lower in ["/menu", "menu", "/help", "help", "hướng dẫn", "5"]:
            return True, self.get_menu_text()

        # 3. Phím 1 (Hướng dẫn lưu)
        if text_lower == "1":
            return True, "Để lưu kiến thức, bạn gõ cú pháp: /save <nội dung cần lưu>\nVí dụ: /save Quy định họp lúc 9h sáng thứ 2."

        # 4. View Knowledge: /knowledge, phím 2
        if text_lower in ["/knowledge", "xem kiến thức", "kho kiến thức", "kiến thức đã lưu", "2"]:
            knowledge_text = knowledge_service.get_knowledge_summary(chat_id, limit=5)
            if not knowledge_text:
                return True, "Nhóm mình hiện chưa lưu kiến thức nào. Bạn có thể dùng lệnh /save <nội dung> để lưu nhé!"
            return True, f"📚 KHO KIẾN THỨC ĐÃ LƯU CỦA NHÓM:\n\n{knowledge_text}"

        # 5. Summarize: /summary, phím 3
        if text_lower in ["/summary", "/tonghop", "tổng hợp nhóm", "tóm tắt 12h", "tổng hợp 12h", "3"]:
            summary = knowledge_service.summarize_and_store(chat_id, hours=settings.MAX_CONTEXT_HOURS)
            return True, f"📊 TỔNG HỢP KIẾN THỨC THẢO LUẬN 12 GIỜ QUA:\n\n{summary}"

        # 6. Clear Memory: /clear, phím 4
        if text_lower in ["/clear", "/reset", "xóa bộ nhớ", "quên đi", "4"]:
            # Check Admin permission if configured
            if settings.admin_ids and user_id not in settings.admin_ids:
                return True, "⚠️ Bạn không có quyền quản trị để xóa bộ nhớ của nhóm."
            context_service.clear_context(chat_id)
            return True, "🧹 Đã xóa lịch sử trò chuyện gần đây của nhóm! Kho kiến thức đã lưu (/knowledge) vẫn được giữ nguyên an toàn."

        # 7. Manual Save: /save <content>, ghi nhớ: <content>
        save_match = re.match(r"^(?:/save|ghi nhớ[:\s]|lưu lại[:\s]|lưu kiến thức[:\s]|lưu trữ[:\s])\s*(.*)$", cleaned_text, re.IGNORECASE)
        if save_match:
            content_to_save = save_match.group(1).strip()
            if not content_to_save:
                return True, "Bạn hãy nhập nội dung cần lưu sau lệnh /save nhé (ví dụ: /save Dự án A bắt đầu từ thứ 2)."
            
            # Check Admin permission if configured
            if settings.admin_ids and user_id not in settings.admin_ids:
                return True, "⚠️ Bạn không có quyền quản trị để lưu kiến thức vào kho nhóm."

            knowledge_service.save(
                chat_id=chat_id,
                content=content_to_save,
                created_by=sender_name or "Thành viên",
                topic="Kiến thức ghi nhớ"
            )
            return True, f"✅ Đã lưu lại kiến thức vào kho của nhóm:\n• {content_to_save}"

        return False, None


command_handler = CommandHandler()
