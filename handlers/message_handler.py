import logging
from typing import Dict, Any, List, Optional
from config.settings import settings
from services.zalo_client import zalo_client
from services.llm_service import llm_service
from services.context_service import context_service
from services.knowledge_service import knowledge_service
from services.semantic_memory_service import semantic_memory_service
from services.quota_service import quota_service
from services.aggregator_service import aggregator_service
from services.formatter import clean_mention, clean_markdown_for_zalo, strip_quota_badges
from handlers.command_handler import command_handler

logger = logging.getLogger(__name__)


class MessageHandler:
    def process_webhook_event(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry point for incoming Zalo webhook event.
        Dispatches commands immediately, and debounces conversation messages into batches.
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
        message_id = message.get("message_id") or data.get("message_id") or message.get("msg_id") or data.get("msg_id")

        # Quoted / Reply-to message context
        reply_to_obj = message.get("reply_to_message") or data.get("reply_to_message") or {}
        reply_to_text = reply_to_obj.get("text", "") if isinstance(reply_to_obj, dict) else ""
        reply_to_sender = reply_to_obj.get("from", {}).get("display_name", "") if isinstance(reply_to_obj, dict) else ""

        # Ignore non-text or empty events
        if not raw_text or not chat_id:
            return {"status": "ignored", "event": event_type}

        # Access Control: Check if group is allowed
        if settings.allowed_groups and str(chat_id) not in settings.allowed_groups:
            logger.warning(f"Ignored message from unauthorized chat_id: {chat_id}")
            return {"status": "forbidden", "chat_id": chat_id}

        cleaned_text = clean_mention(raw_text)

        # 1. Immediate Execution for System & Admin Commands
        is_cmd, cmd_reply = command_handler.handle_command(
            cleaned_text=cleaned_text,
            chat_id=str(chat_id),
            user_id=str(user_id),
            sender_name=sender_name
        )

        if is_cmd:
            logger.info(f"Executing command directly for {sender_name} ({user_id}): {cleaned_text[:50]}")
            if cmd_reply:
                zalo_client.send_message(
                    chat_id=str(chat_id),
                    text=cmd_reply,
                    reply_to_message_id=str(message_id) if message_id else None
                )
            return {"status": "command_processed", "chat_id": chat_id}

        # 2. Queue conversational messages into Debounce Aggregator
        event_info = {
            "chat_id": str(chat_id),
            "user_id": str(user_id),
            "sender_name": sender_name,
            "raw_text": raw_text,
            "cleaned_text": cleaned_text,
            "event_type": event_type,
            "message_id": str(message_id) if message_id else None,
            "reply_to_text": reply_to_text,
            "reply_to_sender": reply_to_sender
        }

        aggregator_service.enqueue_message(
            chat_id=str(chat_id),
            event_data=event_info,
            flush_callback=self._process_aggregated_batch
        )

        return {"status": "queued_for_debounce", "chat_id": chat_id}

    def _process_aggregated_batch(self, chat_id: str, events: List[Dict[str, Any]]):
        """
        Executes after debounce timer expires (no new messages for 2.5s).
        Gathers all consecutive texts into a single prompt, saving tokens & sending 1 unified response.
        """
        if not events:
            return

        latest_event = events[-1]
        user_id = latest_event["user_id"]
        sender_name = latest_event["sender_name"]
        event_type = latest_event["event_type"]
        latest_message_id = latest_event.get("message_id")

        # 1. Combine consecutive text messages and incorporate quoted reply context
        if len(events) == 1:
            e = events[0]
            txt = e["cleaned_text"]
            if e.get("reply_to_text"):
                r_sender = e.get("reply_to_sender") or "tin nhắn"
                combined_cleaned_text = f"[Trả lời tin nhắn của {r_sender}: \"{e['reply_to_text']}\"]\n{txt}"
            else:
                combined_cleaned_text = txt
        else:
            # Multi-line consecutive messages
            lines = []
            for e in events:
                txt = e.get("cleaned_text", "")
                if e.get("reply_to_text"):
                    r_sender = e.get("reply_to_sender") or "tin nhắn"
                    lines.append(f"[Trả lời tin nhắn của {r_sender}: \"{e['reply_to_text']}\"] {txt}")
                else:
                    lines.append(txt)
            combined_cleaned_text = "\n".join(lines)
            logger.info(f"Aggregated {len(events)} consecutive messages from {sender_name} ({chat_id}):\n{combined_cleaned_text}")

        # 2. Check 1-1 Private Chat Quota & Spam Protection (1 turn per aggregated batch)
        can_process, is_silent, quota_notice, quota_badge = quota_service.check_user_quota(
            chat_id=str(chat_id),
            user_id=str(user_id),
            display_name=sender_name
        )

        if is_silent:
            logger.warning(f"Silently dropped batch from {sender_name} ({user_id}) - Quota exceeded/blocked")
            return

        if not can_process:
            if quota_notice:
                zalo_client.send_message(
                    chat_id=str(chat_id),
                    text=quota_notice,
                    reply_to_message_id=latest_message_id
                )
            return

        # 3. Load Episodic Context (Rolling Summary + Recent Turns) & Group Knowledge
        rolling_summary, history = context_service.get_optimized_context(
            str(chat_id),
            max_hours=settings.MAX_CONTEXT_HOURS,
            recent_count=settings.RECENT_MESSAGES_COUNT
        )
        knowledge_base = knowledge_service.get_knowledge_summary(str(chat_id), limit=3)

        # 4. Semantic Long-Term Memory (RAG + Vector Embedding Search)
        relevant_mems = semantic_memory_service.search_relevant_memories(
            chat_id=str(chat_id),
            query=combined_cleaned_text,
            top_k=3,
            min_similarity=0.35
        )
        semantic_context = semantic_memory_service.format_memories_for_prompt(relevant_mems)

        # 5. Format prompt with sender name
        prompt_with_sender = f"{sender_name}: {combined_cleaned_text}" if sender_name else combined_cleaned_text

        # 6. Generate AI reply with Tri-Tier Context
        raw_ai_reply = llm_service.generate_reply(
            prompt=prompt_with_sender,
            history=history,
            knowledge_base=knowledge_base,
            rolling_summary=rolling_summary,
            semantic_context=semantic_context
        )

        cleaned_ai_reply = strip_quota_badges(raw_ai_reply)
        reply_text = clean_markdown_for_zalo(cleaned_ai_reply)

        # 7. Append transient quota badge if applicable
        final_send_text = f"{reply_text}{quota_badge}" if quota_badge else reply_text

        # 8. Send unified message back to Zalo quoting the user's message
        zalo_client.send_message(
            chat_id=str(chat_id),
            text=final_send_text,
            reply_to_message_id=latest_message_id
        )

        # 9. Save turn to conversation database
        saved_msg = f"{sender_name}: {combined_cleaned_text}" if sender_name else combined_cleaned_text
        context_service.save_turn(str(chat_id), saved_msg, reply_text, event_type=event_type)

        # 10. Check & rollup summary in background (Episodic Memory compaction)
        context_service.trigger_async_summary_update(str(chat_id))


message_handler = MessageHandler()
