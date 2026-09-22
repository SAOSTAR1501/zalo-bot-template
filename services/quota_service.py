import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional, List, Dict
from config.settings import settings
from database.connection import SessionLocal
from database.models import UserQuota
from services.zalo_client import zalo_client

logger = logging.getLogger(__name__)


class QuotaService:
    """
    Access control & Rate limiting for 1-1 Private chats.
    - Admin (Mai Công Sao): Unlimited access & full admin controls
    - Free tier: 10 messages
    - Plans:
        • +N tin (10, 20, 50, 100)
        • homnay / today (đến 23:59 hôm nay)
        • tuannay / week (7 ngày)
        • thangnay / month (30 ngày)
        • vinhvien / full (vĩnh viễn)
    - Blocked users: immediately dropped silently
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
            quota_badge (str | None): Badge to append to live Zalo message.
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
                    is_blocked=False,
                    plan_name="free",
                    spam_warnings_sent=0,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(record)
                db.commit()
                badge = f"\n\n(💡 Tin nhắn 1/{settings.FREE_MESSAGE_QUOTA} miễn phí)"
                return True, False, None, badge

            # 3. Check if user is BLOCKED by Admin
            if record.is_blocked:
                logger.warning(f"Silently dropped message from BLOCKED user: {display_name} ({user_id})")
                return False, True, None, None

            # 4. Check Approved / Subscription plans
            if record.is_approved:
                # Check expiration date for duration plans (today, week, month)
                if record.expire_at:
                    if datetime.utcnow() <= record.expire_at:
                        record.message_count += 1
                        record.updated_at = datetime.utcnow()
                        db.commit()
                        return True, False, None, None
                    else:
                        # Plan has expired! Revert to expired status
                        record.is_approved = False
                        record.plan_name = "expired"
                        record.spam_warnings_sent = 1
                        record.updated_at = datetime.utcnow()
                        db.commit()
                        notice = "Gói sử dụng của bạn đã hết hạn, liên hệ Admin Sao đẹp trai để được gia hạn thêm."
                        return False, False, notice, None
                else:
                    # Permanent unlimited
                    record.message_count += 1
                    record.updated_at = datetime.utcnow()
                    db.commit()
                    return True, False, None, None

            # 5. Check count-based quota (Free tier or +N tin)
            if record.message_count < record.max_quota:
                record.message_count += 1
                record.updated_at = datetime.utcnow()
                db.commit()

                # If this turn reaches the limit, alert Admin with quick-approval shortcuts
                if record.message_count >= record.max_quota:
                    self._notify_admin_quota_exhausted(str(user_id), str(record.display_name or display_name))

                badge = f"\n\n(💡 Tin nhắn {record.message_count}/{record.max_quota} miễn phí)"
                return True, False, None, badge

            # 6. Exceeded quota
            record.spam_warnings_sent += 1
            record.updated_at = datetime.utcnow()
            db.commit()

            if record.spam_warnings_sent <= settings.MAX_SPAM_WARNINGS:
                notice = "Bạn sử dụng hết 10 tin nhắn miễn phí rồi, liên hệ Admin Sao đẹp trai để được mở rộng quyền"
                return False, False, notice, None
            else:
                # Silent drop to save monthly Zalo messages
                logger.warning(f"User {user_id} ({display_name}) exceeded quota & spammed > {settings.MAX_SPAM_WARNINGS} times. Dropping silently.")
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
                    f"👉 Cú pháp duyệt hạn mức:\n"
                    f"• /accept {user_id} 10 (Thêm 10 tin)\n"
                    f"• /accept {user_id} homnay (Mở hôm nay)\n"
                    f"• /accept {user_id} tuannay (Mở 7 ngày)\n"
                    f"• /accept {user_id} thangnay (Mở 30 ngày)\n"
                    f"• /accept {user_id} vinhvien (Mở vĩnh viễn)\n"
                    f"• /block {user_id} (Chặn người này)"
                )
                zalo_client.send_message(admin_id, alert_text)
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")

    def apply_plan(self, target_user_id: str, plan_input: str) -> Tuple[bool, str]:
        """
        Applies a predefined quota plan to a user.
        Supported plans:
            - Number (10, 20, 50, 100): adds +N messages
            - homnay / today / ngay: unlimited until end of today
            - tuannay / week / tuan: unlimited for 7 days
            - thangnay / month / thang: unlimited for 30 days
            - vinhvien / full / vohan / permanent: unlimited forever
        """
        plan_clean = plan_input.strip().lower() if plan_input else "vinhvien"
        now = datetime.utcnow()

        db = SessionLocal()
        try:
            record = db.query(UserQuota).filter(UserQuota.user_id == str(target_user_id)).first()
            if not record:
                record = UserQuota(
                    user_id=str(target_user_id),
                    display_name=f"User_{target_user_id[:6]}",
                    message_count=0,
                    max_quota=settings.FREE_MESSAGE_QUOTA,
                    is_approved=False,
                    is_blocked=False,
                    plan_name="free",
                    spam_warnings_sent=0,
                    created_at=now,
                    updated_at=now
                )
                db.add(record)

            record.is_blocked = False
            record.spam_warnings_sent = 0
            record.updated_at = now

            name = record.display_name or target_user_id
            user_msg = ""
            admin_msg = ""

            # Case 1: Numeric count (+10, +20, +50...)
            if plan_clean.isdigit():
                add_count = int(plan_clean)
                base_quota = max(record.message_count, record.max_quota)
                record.max_quota = base_quota + add_count
                record.is_approved = False
                record.plan_name = f"+{add_count}"
                record.expire_at = None
                remaining = record.max_quota - record.message_count
                user_msg = f"🎉 Admin Sao đẹp trai đã cộng thêm {add_count} tin nhắn cho bạn! (Hạn mức còn lại: {remaining} tin). Bạn có thể tiếp tục trò chuyện nhé. 😊"
                admin_msg = f"✅ Đã cộng thêm {add_count} tin nhắn cho {name} (ID: {target_user_id}). Hạn mức mới: {record.message_count}/{record.max_quota} (còn {remaining} tin)."

            # Case 2: Today (Mở hôm nay)
            elif plan_clean in ["homnay", "today", "ngay", "1ngay"]:
                # End of today UTC (approx 24 hours)
                record.expire_at = now + timedelta(hours=24)
                record.is_approved = True
                record.plan_name = "today"
                user_msg = "🎉 Bạn đã được Admin Sao đẹp trai mở quyền sử dụng KHÔNG GIỚI HẠN trong ngày hôm nay! Hãy thoải mái trò chuyện cùng bot nhé. 😊"
                admin_msg = f"✅ Đã mở quyền sử dụng HÔM NAY cho {name} (ID: {target_user_id}) thành công!"

            # Case 3: Week (Mở tuần này - 7 ngày)
            elif plan_clean in ["tuannay", "week", "tuan", "7ngay"]:
                record.expire_at = now + timedelta(days=7)
                record.is_approved = True
                record.plan_name = "week"
                user_msg = "🎉 Bạn đã được Admin Sao đẹp trai mở quyền sử dụng KHÔNG GIỚI HẠN trong 7 NGÀY! Hãy thoải mái trò chuyện cùng bot nhé. 😊"
                admin_msg = f"✅ Đã mở quyền sử dụng 7 NGÀY cho {name} (ID: {target_user_id}) thành công!"

            # Case 4: Month (Mở tháng này - 30 ngày)
            elif plan_clean in ["thangnay", "month", "thang", "30ngay"]:
                record.expire_at = now + timedelta(days=30)
                record.is_approved = True
                record.plan_name = "month"
                user_msg = "🎉 Bạn đã được Admin Sao đẹp trai mở quyền sử dụng KHÔNG GIỚI HẠN trong 30 NGÀY! Hãy thoải mái trò chuyện cùng bot nhé. 😊"
                admin_msg = f"✅ Đã mở quyền sử dụng 30 NGÀY cho {name} (ID: {target_user_id}) thành công!"

            # Case 5: Permanent / Unlimited (Vĩnh viễn)
            elif plan_clean in ["vinhvien", "full", "vohan", "permanent", "unlimited"]:
                record.expire_at = None
                record.is_approved = True
                record.plan_name = "permanent"
                user_msg = "🎉 Bạn đã được Admin Sao đẹp trai cấp quyền sử dụng VĨNH VIỄN KHÔNG GIỚI HẠN! Bạn có thể thoải mái trò chuyện cùng bot nhé. 😊"
                admin_msg = f"✅ Đã cấp quyền VĨNH VIỄN cho {name} (ID: {target_user_id}) thành công!"

            else:
                return False, f"Gói '{plan_input}' không hợp lệ. Các gói hỗ trợ: 10, 20, 50, homnay, tuannay, thangnay, vinhvien."

            db.commit()

            # Notify user
            if user_msg:
                try:
                    zalo_client.send_message(str(target_user_id), user_msg)
                except Exception as e:
                    logger.warning(f"Could not send plan notification to user {target_user_id}: {e}")

            return True, admin_msg
        except Exception as e:
            logger.error(f"Error applying plan to {target_user_id}: {e}")
            return False, f"Lỗi: {e}"
        finally:
            db.close()

    def block_user(self, target_user_id: str) -> Tuple[bool, str]:
        """Blocks a user completely."""
        db = SessionLocal()
        try:
            record = db.query(UserQuota).filter(UserQuota.user_id == str(target_user_id)).first()
            if not record:
                record = UserQuota(
                    user_id=str(target_user_id),
                    display_name=f"User_{target_user_id[:6]}",
                    is_blocked=True,
                    is_approved=False,
                    plan_name="blocked",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(record)
            else:
                record.is_blocked = True
                record.is_approved = False
                record.plan_name = "blocked"
                record.updated_at = datetime.utcnow()

            db.commit()
            name = record.display_name or target_user_id
            return True, f"🚫 Đã CHẶN người dùng {name} (ID: {target_user_id}). Bot sẽ không phản hồi bất kỳ tin nhắn nào từ người này."
        except Exception as e:
            logger.error(f"Error blocking user {target_user_id}: {e}")
            return False, f"Lỗi khi chặn: {e}"
        finally:
            db.close()

    def unblock_user(self, target_user_id: str) -> Tuple[bool, str]:
        """Unblocks a user."""
        db = SessionLocal()
        try:
            record = db.query(UserQuota).filter(UserQuota.user_id == str(target_user_id)).first()
            if not record:
                return False, f"Không tìm thấy người dùng ID: {target_user_id}"

            record.is_blocked = False
            record.spam_warnings_sent = 0
            record.updated_at = datetime.utcnow()
            db.commit()
            name = record.display_name or target_user_id
            return True, f"✅ Đã BỎ CHẶN người dùng {name} (ID: {target_user_id}) thành công!"
        except Exception as e:
            return False, f"Lỗi: {e}"
        finally:
            db.close()

    def list_users(self, limit: int = 15) -> str:
        """Returns formatted string of recent users and their quotas."""
        db = SessionLocal()
        try:
            records = db.query(UserQuota).order_by(UserQuota.updated_at.desc()).limit(limit).all()
            if not records:
                return "Chưa có người dùng nào tương tác 1-1."
            lines = ["👥 DANH SÁCH NGƯỜI DÙNG & HẠN MỨC:"]
            for r in records:
                if r.is_blocked:
                    status = "🚫 ĐÃ BỊ CHẶN"
                elif r.is_approved:
                    if r.expire_at:
                        exp_str = r.expire_at.strftime("%d/%m %H:%M")
                        status = f"Gói {r.plan_name} (Hạn: {exp_str})"
                    else:
                        status = "Vĩnh viễn (Không giới hạn)"
                else:
                    status = f"{r.message_count}/{r.max_quota} tin"
                    if r.message_count >= r.max_quota:
                        status += f" (Hết hạn, spam: {r.spam_warnings_sent})"
                lines.append(f"• {r.display_name or 'N/A'} (ID: {r.user_id}): {status}")
            return "\n".join(lines)
        except Exception as e:
            return f"Lỗi tải danh sách: {e}"
        finally:
            db.close()


quota_service = QuotaService()
