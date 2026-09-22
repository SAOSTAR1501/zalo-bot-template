import logging
from typing import Dict, Any, Optional
from config.settings import settings
from services.zalo_client import zalo_client
from services.llm_service import llm_service
from services.context_service import context_service
from services.knowledge_service import knowledge_service
from services.formatter import clean_mention, clean_markdown_for_zalo
from handlers.command_handler import command_handler

logger = logging.getLogger(__name__)


class MessageHandler:
    def process_webhook_event(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry point for incoming Zalo webhook event.
        """
        event_type = data.get("event_name", "") or data.get("event_type", "")
        message = data.get("message", {}) if isinstance(data.get("message"), dict) else {}
        from_user = message.get("from", {}) if isinstance(message.get("from"), dict) else (data.get("from", {}) if isinstance(data.get("from"), dict) else {})

        # Extract chat_id (group or 1-1)
        chat_id = (
            message.get("chat", {}).get("id")
            or data.get("chat", {}).get("id")
            or data.get("chat_id")
            or data.get("sender", {}).get("id")
        )
        user_id = from_user.get("id") or data.get("sender", {}).get("id") or chat_id
        sender_name = from_user.get("display_name", "")
        raw_text = message.get("text", "") or data.get("text", "")

        logger.info(f"Incoming event: type={event_type}, chat_id={chat_id}, user={sender_name}({user_id}), text={raw_text[:200]}")

        # Ignore non-text or empty events
        if not raw_text or not chat_id:
            return {"status": "ignored", "event": event_type}

        # Access Control: Check if group is allowed
        if settings.allowed_groups and str(chat_id) not in settings.allowed_groups:
            logger.warning(f"Ignored message from unauthorized chat_id: {chat_id}")
            return {"status": "forbidden", "chat_id": chat_id}

        # 1. Clean mention prefix (@Bot_Name)
        cleaned_text = clean_mention(raw_text)

        # 2. Check for built-in Commands / Menu
        is_cmd, cmd_reply = command_handler.handle_command(
            cleaned_text=cleaned_text,
            chat_id=str(chat_id),
            user_id=str(user_id),
            sender_name=sender_name
        )

        if is_cmd and cmd_reply:
            reply_text = cmd_reply
        else:
            # 3. Load Episodic Context (Rolling Summary + Recent Turns) & Group Knowledge
            rolling_summary, history = context_service.get_optimized_context(
                str(chat_id),
                max_hours=settings.MAX_CONTEXT_HOURS,
                recent_count=settings.RECENT_MESSAGES_COUNT
            )
            knowledge_base = knowledge_service.get_knowledge_summary(str(chat_id), limit=3)

            # Format user prompt with sender name for group clarity
            prompt_with_sender = f"{sender_name}: {cleaned_text}" if sender_name else cleaned_text

            # 4. Generate AI reply
            raw_ai_reply = llm_service.generate_reply(
                prompt=prompt_with_sender,
                history=history,
                knowledge_base=knowledge_base,
                rolling_summary=rolling_summary
            )
            reply_text = clean_markdown_for_zalo(raw_ai_reply)

        # 5. Send message back to Zalo
        send_res = zalo_client.send_message(str(chat_id), reply_text)

        # 6. Save turn to conversation database
        saved_msg = f"{sender_name}: {cleaned_text}" if sender_name else cleaned_text
        context_service.save_turn(str(chat_id), saved_msg, reply_text, event_type=event_type)

        # 7. Check & rollup summary in background (Episodic Memory compaction)
        context_service.trigger_async_summary_update(str(chat_id))

        return {"status": "processed", "send_res": send_res}


message_handler = MessageHandler()

