import logging
from datetime import datetime
from typing import Tuple, Optional, List, Dict
from config.settings import settings
from database.connection import SessionLocal
from database.models import UserQuota
from services.zalo_client import zalo_client

logger = logging.getLogger(__name__)


class QuotaService:
    """
    Access control & Rate limiting for 1-1 Private chats.
    - Admin (Mai Công Sao): Unlimited
    - Free users: 10 messages
    - Exceeded quota: warns up to 3 times, then silent drop to preserve monthly quota.
    """

    def is_admin(self, user_id: str) -> bool:
        if not user_id:
            return False
        return str(user_id) in settings.admin_ids

    def check_user_quota(
        self,
        chat_id: str,
        user_id: str,
        display_name: str
    ) -> Tuple[bool, bool, Optional[str], Optional[str]]:
        """
        Evaluates message quota for a user.
        Returns:
            can_process (bool): Whether to generate LLM reply.
            is_silent_drop (bool): Whether to drop completely without replying.
            quota_notice_to_user (str | None): Warning / Notice message if blocked.
            quota_badge (str | None): Badge to append to LLM reply (e.g. "[Tin nhắn 3/10 miễn phí]").
        """
        # 1. Group chats are not subject to 1-1 personal rate limits
        if str(chat_id) != str(user_id):
            return True, False, None, None

        # 2. Admin is always unlimited
        if self.is_admin(user_id):
            return True, False, None, None

        db = SessionLocal()
        try:
            record = db.query(UserQuota).filter(UserQuota.user_id == str(user_id)).first()

            # First time user
            if not record:
                record = UserQuota(
                    user_id=str(user_id),
                    display_name=str(display_name) if display_name else "Người dùng mới",
                    message_count=1,
                    max_quota=settings.FREE_MESSAGE_QUOTA,
                    is_approved=False,
                    spam_warnings_sent=0,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(record)
                db.commit()
                badge = f"\n\n(💡 Tin nhắn 1/{settings.FREE_MESSAGE_QUOTA} miễn phí)"
                return True, False, None, badge

            # Whitelisted / Approved user
            if record.is_approved:
                record.message_count += 1
                record.updated_at = datetime.utcnow()
                db.commit()
                return True, False, None, None

            # Within free quota
            if record.message_count < record.max_quota:
                record.message_count += 1
                record.updated_at = datetime.utcnow()
                db.commit()

                # If this turn reaches the limit, alert Admin
                if record.message_count >= record.max_quota:
                    self._notify_admin_quota_exhausted(str(user_id), str(record.display_name or display_name))

                badge = f"\n\n(💡 Tin nhắn {record.message_count}/{record.max_quota} miễn phí)"
                return True, False, None, badge

            # Exceeded free quota
            record.spam_warnings_sent += 1
            record.updated_at = datetime.utcnow()
            db.commit()

            if record.spam_warnings_sent <= settings.MAX_SPAM_WARNINGS:
                notice = "Bạn sử dụng hết 10 tin nhắn miễn phí rồi, liên hệ Admin Sao đẹp trai để được mở rộng quyền"
                return False, False, notice, None
            else:
                # Spamming > 3 times -> Silent drop to protect monthly API quota
                logger.warning(f"User {user_id} ({display_name}) exceeded quota and spammed > {settings.MAX_SPAM_WARNINGS} times. Dropping silently.")
                return False, True, None, None

        except Exception as e:
            logger.error(f"Error checking user quota: {e}")
            return True, False, None, None
        finally:
            db.close()

    def _notify_admin_quota_exhausted(self, user_id: str, display_name: str):
        """Sends alert message to Admin when a user finishes free tier."""
        for admin_id in settings.admin_ids:
            try:
                alert_text = (
                    f"🔔 THÔNG BÁO ADMIN:\n"
                    f"Người dùng: {display_name}\n"
                    f"User ID: {user_id}\n"
                    f"Đã sử dụng hết {settings.FREE_MESSAGE_QUOTA} tin nhắn miễn phí.\n\n"
                    f"👉 Để cấp quyền không giới hạn, hãy gửi lệnh:\n/accept {user_id}"
                )
                zalo_client.send_message(admin_id, alert_text)
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")

    def approve_user(self, target_user_id: str) -> Tuple[bool, str]:
        """Approves a user for unlimited access."""
        db = SessionLocal()
        try:
            record = db.query(UserQuota).filter(UserQuota.user_id == str(target_user_id)).first()
            if not record:
                record = UserQuota(
                    user_id=str(target_user_id),
                    display_name=f"User_{target_user_id[:6]}",
                    message_count=0,
                    max_quota=settings.FREE_MESSAGE_QUOTA,
                    is_approved=True,
                    spam_warnings_sent=0,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(record)
            else:
                record.is_approved = True
                record.spam_warnings_sent = 0
                record.updated_at = datetime.utcnow()

            db.commit()

            # Send welcome message to approved user
            try:
                zalo_client.send_message(
                    str(target_user_id),
                    "🎉 Bạn đã được Admin Sao đẹp trai cấp quyền sử dụng không giới hạn! Bạn có thể thoải mái trò chuyện cùng bot nhé. 😊"
                )
            except Exception as e:
                logger.warning(f"Could not notify approved user {target_user_id}: {e}")

            name = record.display_name or target_user_id
            return True, f"✅ Đã cấp quyền không giới hạn cho {name} (ID: {target_user_id}) thành công!"
        except Exception as e:
            logger.error(f"Error approving user {target_user_id}: {e}")
            return False, f"Lỗi khi duyệt người dùng: {e}"
        finally:
            db.close()

    def add_quota_to_user(self, target_user_id: str, additional_count: int) -> Tuple[bool, str]:
        """
        Adds additional message quota to a user instead of granting full unlimited access.
        """
        if additional_count <= 0:
            return False, "Số lượng tin nhắn cộng thêm phải lớn hơn 0."

        db = SessionLocal()
        try:
            record = db.query(UserQuota).filter(UserQuota.user_id == str(target_user_id)).first()
            if not record:
                record = UserQuota(
                    user_id=str(target_user_id),
                    display_name=f"User_{target_user_id[:6]}",
                    message_count=0,
                    max_quota=settings.FREE_MESSAGE_QUOTA + additional_count,
                    is_approved=False,
                    spam_warnings_sent=0,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(record)
            else:
                # Calculate new max quota from current usage
                base_quota = max(record.message_count, record.max_quota)
                record.max_quota = base_quota + additional_count
                record.is_approved = False  # Keep as quota-based
                record.spam_warnings_sent = 0  # Unblock spam
                record.updated_at = datetime.utcnow()

            db.commit()

            remaining = record.max_quota - record.message_count
            name = record.display_name or target_user_id

            # Send notification message to the user
            try:
                zalo_client.send_message(
                    str(target_user_id),
                    f"🎉 Admin Sao đẹp trai đã cộng thêm {additional_count} tin nhắn cho bạn! (Hạn mức còn lại: {remaining} tin). Bạn có thể tiếp tục trò chuyện cùng bot nhé. 😊"
                )
            except Exception as e:
                logger.warning(f"Could not notify user {target_user_id}: {e}")

            return True, f"✅ Đã cộng thêm {additional_count} tin nhắn cho {name} (ID: {target_user_id}) thành công! Hạn mức mới: {record.message_count}/{record.max_quota} (còn {remaining} tin)."
        except Exception as e:
            logger.error(f"Error adding quota to {target_user_id}: {e}")
            return False, f"Lỗi cộng tin nhắn: {e}"
        finally:
            db.close()

    def set_custom_quota(self, target_user_id: str, new_quota: int) -> Tuple[bool, str]:
        """Sets custom message limit for a user."""
        return self.add_quota_to_user(target_user_id, new_quota)


    def list_users(self, limit: int = 15) -> str:
        """Returns formatted string of recent users and their quotas."""
        db = SessionLocal()
        try:
            records = db.query(UserQuota).order_by(UserQuota.updated_at.desc()).limit(limit).all()
            if not records:
                return "Chưa có người dùng nào tương tác 1-1."
            lines = ["👥 DANH SÁCH NGƯỜI DÙNG & HẠN MỨC:"]
            for r in records:
                status = "Vô hạn (Đã duyệt)" if r.is_approved else f"{r.message_count}/{r.max_quota} tin"
                if not r.is_approved and r.message_count >= r.max_quota:
                    status += f" (Hết hạn, spam: {r.spam_warnings_sent})"
                lines.append(f"• {r.display_name or 'N/A'} (ID: {r.user_id}): {status}")
            return "\n".join(lines)
        except Exception as e:
            return f"Lỗi tải danh sách: {e}"
        finally:
            db.close()


quota_service = QuotaService()
