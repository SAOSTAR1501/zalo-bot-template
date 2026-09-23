import re
from typing import Optional, Tuple
from config.settings import settings
from services.context_service import context_service
from services.knowledge_service import knowledge_service
from services.sticker_service import sticker_service


class CommandHandler:
    @staticmethod
    def get_menu_text(is_admin: bool = False) -> str:
        menu = (
            "📋 MENU CHỨC NĂNG CỦA BOT:\n\n"
            "1️⃣ /save <nội dung> : Lưu kiến thức quan trọng vào kho nhóm\n"
            "2️⃣ /knowledge : Xem kho kiến thức đã lưu trữ\n"
            "3️⃣ /summary : Tóm tắt nội dung thảo luận 12 giờ qua\n"
            "4️⃣ /clear : Xóa lịch sử trò chuyện ngắn hạn gần đây\n"
            "5️⃣ /help : Xem lại menu hướng dẫn này\n"
        "6️⃣ /sticker : Xem nhanh kho sticker (30 bộ phổ biến)\n"
        "   /sticker list : Xem toàn bộ danh sách bộ sticker\n"
        "   /sticker <tên bộ> : Gửi ngẫu nhiên 1 sticker từ bộ đó\n"
        "   • Ví dụ: /sticker Bư Mặt Ngáo\n"
        "   • Dữ liệu lấy từ https://stickers.zaloapp.com/\n\n"
            "👉 Trong nhóm chat, hãy @mention bot hoặc trả lời (quote) tin nhắn của bot để bot tự động tham gia.\n"
            "👉 Trong chat riêng, bạn chỉ cần gửi tin nhắn bất kỳ là bot sẽ trả lời.\n"
            "👉 Bot có thể tự động gửi sticker phù hợp với nội dung câu trả lời."
        )
        if is_admin:
            menu += (
                "\n\n👑 QUẢN TRỊ VIÊN (ADMIN ONLY):\n"
                "• /accept <user_id> [gói] : Cấp / Đổi gói linh hoạt\n"
                "  - Cấp số tin: 10, 15, 20, 50, 100 (tùy ý)\n"
                "  - Theo giờ: 2h, 5 giờ, 12h\n"
                "  - Theo ngày: homnay, 3 ngày, tuannay (7 ngày)\n"
                "  - Theo tháng: thangnay (30 ngày), 2 tháng\n"
                "  - Vĩnh viễn: vinhvien\n"
                "  - Reset mặc định: reset (10 tin miễn phí)\n"
                "• /block <user_id> : Khóa / Chặn người dùng vĩnh viễn\n"
                "• /unblock <user_id> : Mở khóa người dùng\n"
                "• /users : Xem danh sách người dùng & hạn mức"
            )
        return menu

    def handle_command(self, cleaned_text: str, chat_id: str, user_id: str, sender_name: str) -> Tuple[bool, Optional[str]]:
        """
        Returns (is_command, reply_text).
        If is_command is False, message should be dispatched to LLM.
        """
        from services.quota_service import quota_service
        is_admin_user = quota_service.is_admin(user_id)
        text_lower = cleaned_text.lower().strip()

        # 1. Start / Hello
        if text_lower in ["/start", "/hello", "hello", "hi", "xin chào", "chào"]:
            name_str = f" {sender_name}" if sender_name else ""
            reply = f"Xin chào{name_str}! Mình là Bot Sao Assistant.\n\n" + self.get_menu_text(is_admin=is_admin_user)
            return True, reply

        # 2. Menu / Help / Phím 5
        if text_lower in ["/menu", "menu", "/help", "help", "hướng dẫn", "5"]:
            return True, self.get_menu_text(is_admin=is_admin_user)

        # 2b. Plain /sticker without argument: show short preview of the catalog
        if text_lower == "/sticker" or text_lower == "sticker":
            return True, sticker_service.list_catalog(full=False)

        # 2c. /sticker list/all: show full catalog
        if text_lower in ["/sticker list", "/sticker all", "sticker list", "sticker all"]:
            return True, sticker_service.list_catalog(full=True)

        # 2d. /sticker <tên bộ>: send a random sticker from that pack
        sticker_match = re.match(r"^(?:/sticker|sticker)\s+(.+)$", cleaned_text, re.IGNORECASE)
        if sticker_match:
            requested = sticker_match.group(1).strip()
            item = sticker_service.get_sticker(requested)
            if item:
                sticker_id, preview_url = item
                # Return a marker so message_handler can dispatch via sendSticker.
                return True, f"[STICKER:{sticker_id}|{preview_url}]"
            return True, f"❓ Bot chưa có bộ sticker '{requested}'.\n{sticker_service.list_catalog(full=False)}"

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
            if not is_admin_user and settings.admin_ids:
                return True, "⚠️ Bạn không có quyền quản trị để xóa bộ nhớ của nhóm."
            context_service.clear_context(chat_id)
            return True, "🧹 Đã xóa lịch sử trò chuyện gần đây của nhóm! Kho kiến thức đã lưu (/knowledge) vẫn được giữ nguyên an toàn."

        # 7. Manual Save: /save <content>, ghi nhớ: <content>
        save_match = re.match(r"^(?:/save|ghi nhớ[:\s]|lưu lại[:\s]|lưu kiến thức[:\s]|lưu trữ[:\s])\s*(.*)$", cleaned_text, re.IGNORECASE)
        if save_match:
            content_to_save = save_match.group(1).strip()
            if not content_to_save:
                return True, "Bạn hãy nhập nội dung cần lưu sau lệnh /save nhé (ví dụ: /save Dự án A bắt đầu từ thứ 2)."
            
            if settings.admin_ids and not is_admin_user:
                return True, "⚠️ Bạn không có quyền quản trị để lưu kiến thức vào kho nhóm."

            knowledge_service.save(
                chat_id=chat_id,
                content=content_to_save,
                created_by=sender_name or "Thành viên",
                topic="Kiến thức ghi nhớ"
            )

            # Also index into Semantic Long-Term Memory (Vector Embedding)
            from services.semantic_memory_service import semantic_memory_service
            semantic_memory_service.async_auto_index_fact(
                chat_id=chat_id,
                content=content_to_save,
                category="knowledge",
                source_user=sender_name or "Thành viên"
            )

            return True, f"✅ Đã lưu lại kiến thức vào kho của nhóm:\n• {content_to_save}"

        # 8. Admin Command: /accept, /duyet, /setlimit, /limit <user_id> [gói]
        accept_match = re.match(r"^(?:/accept|/duyet|duyệt|/setlimit|/limit)\s+([a-zA-Z0-9_-]+)(?:\s+(.+))?$", cleaned_text, re.IGNORECASE)
        if accept_match:
            if not is_admin_user:
                return True, "⚠️ Lệnh này chỉ dành riêng cho Admin Sao đẹp trai."
            target_uid = accept_match.group(1).strip()
            plan_str = (accept_match.group(2) or "vinhvien").strip()
            ok, msg = quota_service.apply_plan(target_uid, plan_str)
            return True, msg

        # 9. Admin Command: /block <user_id> (Chặn người dùng)
        block_match = re.match(r"^(?:/block|/chan|chặn)\s+([a-zA-Z0-9_-]+)$", cleaned_text, re.IGNORECASE)
        if block_match:
            if not is_admin_user:
                return True, "⚠️ Lệnh này chỉ dành riêng cho Admin Sao đẹp trai."
            target_uid = block_match.group(1).strip()
            ok, msg = quota_service.block_user(target_uid)
            return True, msg

        # 10. Admin Command: /unblock <user_id> (Bỏ chặn người dùng)
        unblock_match = re.match(r"^(?:/unblock|/bochan|bỏ chặn)\s+([a-zA-Z0-9_-]+)$", cleaned_text, re.IGNORECASE)
        if unblock_match:
            if not is_admin_user:
                return True, "⚠️ Lệnh này chỉ dành riêng cho Admin Sao đẹp trai."
            target_uid = unblock_match.group(1).strip()
            ok, msg = quota_service.unblock_user(target_uid)
            return True, msg

        # 11. Admin Command: /users (Danh sách người dùng và hạn mức)
        if text_lower in ["/users", "/danhsach", "danh sách người dùng", "xem hạn mức"]:
            if not is_admin_user:
                return True, "⚠️ Lệnh này chỉ dành riêng cho Admin Sao đẹp trai."
            return True, quota_service.list_users()

        return False, None


command_handler = CommandHandler()



