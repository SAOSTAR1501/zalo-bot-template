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

        # 2. Check 1-1 Private Chat Quota & Spam Protection
        from services.quota_service import quota_service
        can_process, is_silent, quota_notice, quota_badge = quota_service.check_user_quota(
            chat_id=str(chat_id),
            user_id=str(user_id),
            display_name=sender_name
        )

        if is_silent:
            logger.warning(f"Silently dropped message from {sender_name} ({user_id}) - Quota exceeded & spam > {settings.MAX_SPAM_WARNINGS}")
            return {"status": "quota_exceeded_silent", "user_id": user_id}

        if not can_process:
            if quota_notice:
                zalo_client.send_message(str(chat_id), quota_notice)
            return {"status": "quota_exceeded_notified", "user_id": user_id}

        # 3. Check for built-in Commands / Menu
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

            # 4. Semantic Long-Term Memory (RAG + Vector Embedding Search)
            from services.semantic_memory_service import semantic_memory_service
            relevant_mems = semantic_memory_service.search_relevant_memories(
                chat_id=str(chat_id),
                query=cleaned_text,
                top_k=3,
                min_similarity=0.35
            )
            semantic_context = semantic_memory_service.format_memories_for_prompt(relevant_mems)

            # Format user prompt with sender name for group clarity
            prompt_with_sender = f"{sender_name}: {cleaned_text}" if sender_name else cleaned_text

            # 5. Generate AI reply with Tri-Tier Context
            raw_ai_reply = llm_service.generate_reply(
                prompt=prompt_with_sender,
                history=history,
                knowledge_base=knowledge_base,
                rolling_summary=rolling_summary,
                semantic_context=semantic_context
            )
            reply_text = clean_markdown_for_zalo(raw_ai_reply)
            if quota_badge:
                reply_text += quota_badge

        # 6. Send message back to Zalo
        send_res = zalo_client.send_message(str(chat_id), reply_text)

        # 7. Save turn to conversation database
        saved_msg = f"{sender_name}: {cleaned_text}" if sender_name else cleaned_text
        context_service.save_turn(str(chat_id), saved_msg, reply_text, event_type=event_type)


        # 8. Check & rollup summary in background (Episodic Memory compaction)
        context_service.trigger_async_summary_update(str(chat_id))

        return {"status": "processed", "send_res": send_res}



message_handler = MessageHandler()

