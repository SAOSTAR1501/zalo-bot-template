import logging
import random
import re
import threading
import time
from typing import Dict, Any, List, Optional
from config.settings import settings
from services.zalo_client import zalo_client
from services.llm_service import llm_service
from services.context_service import context_service
from services.knowledge_service import knowledge_service
from services.semantic_memory_service import semantic_memory_service
from services.quota_service import quota_service
from services.aggregator_service import aggregator_service
from services.image_service import image_service
from services.sticker_service import sticker_service
from services.image_generation_service import image_generation_service
from services.web_search_service import web_search_service
from services.formatter import (
    clean_mention,
    clean_markdown_for_zalo,
    strip_quota_badges,
    mention_name_for_zalo,
    is_mentioning_bot,
    is_reply_to_bot,
    extract_target_mentions,
)
from handlers.command_handler import command_handler

logger = logging.getLogger(__name__)


def _start_typing_heartbeat(chat_id: str, interval: float = 4.0) -> threading.Event:
    """
    Send repeated typing chat actions until the returned event is set.
    Zalo's typing indicator expires after a few seconds, so we keep it alive
    during long-running operations like image generation.
    """
    stop_event = threading.Event()

    def _heartbeat():
        while not stop_event.is_set():
            try:
                zalo_client.send_chat_action(chat_id, "typing")
            except Exception as e:
                logger.debug(f"Typing heartbeat failed: {e}")
            stop_event.wait(interval)

    thread = threading.Thread(target=_heartbeat, daemon=True)
    thread.start()
    return stop_event


class MessageHandler:
    def __init__(self):
        # Cached bot identity from getMe (lazy loaded on first message).
        self._bot_display_name: Optional[str] = None
        self._bot_user_id: Optional[str] = None
        self._quick_replies: Dict[str, List[str]] = {
            "hello": [
                "Chào {name}! 👋 Mình là Bot Sao Assistant. Hôm nay mình giúp gì được cho bạn?",
                "Xin chào {name}! 😊 Bạn cần mình hỗ trợ gì không?",
                "Chào buổi {time} {name}! 👋",
            ],
            "thanks": [
                "Không có gì {name}! 😊 Rất vui được giúp bạn.",
                "Cảm ơn bạn {name}! 🙌",
                "Rất vui được hỗ trợ {name}! 👍",
            ],
            "bye": [
                "Tạm biệt {name}! 👋 Hẹn gặp lại.",
                "Bye {name}! Chúc bạn một ngày tốt lành. 🌟",
                "Tạm biệt {name}! Cần gì cợc gọi mình nhé. 😊",
            ],
        }

    def _refresh_bot_identity(self):
        """Fetch and cache the bot's own display name and user id from Zalo."""
        if self._bot_display_name and self._bot_user_id:
            return
        try:
            me = zalo_client.get_me()
            if me and me.get("ok"):
                result = me.get("result", {})
                self._bot_display_name = result.get("display_name") or result.get("name") or ""
                self._bot_user_id = result.get("id") or ""
                logger.info(f"Bot identity cached: name={self._bot_display_name}, id={self._bot_user_id}")
        except Exception as e:
            logger.warning(f"Could not cache bot identity: {e}")

    def process_webhook_event(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry point for incoming Zalo webhook event.
        Dispatches commands immediately, and debounces conversation messages & images into batches.
        """
        self._refresh_bot_identity()

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
        message_id = message.get("message_id") or data.get("message_id") or message.get("msg_id") or data.get("msg_id")
        chat_type = (
            message.get("chat", {}).get("chat_type")
            or data.get("chat", {}).get("chat_type")
            or "PRIVATE"
        )

        # Extract photo / image URL if present
        photo_url = (
            message.get("photo_url")
            or data.get("photo_url")
            or (message.get("photo")[-1].get("url") if isinstance(message.get("photo"), list) and message.get("photo") else None)
            or (message.get("photo") if isinstance(message.get("photo"), str) else None)
            or data.get("photo")
            or data.get("url")
        )

        caption_text = message.get("caption", "") or data.get("caption", "") or ""
        raw_text = message.get("text", "") or data.get("text", "") or caption_text

        # Ignore empty events
        if (not raw_text and not photo_url) or not chat_id:
            return {"status": "ignored", "event": event_type}

        # Quoted / Reply-to message context
        reply_to_obj = message.get("reply_to_message") or data.get("reply_to_message") or {}
        reply_to_text = reply_to_obj.get("text", "") if isinstance(reply_to_obj, dict) else ""
        reply_to_sender = reply_to_obj.get("from", {}).get("display_name", "") if isinstance(reply_to_obj, dict) else ""
        is_reply_to_bot_msg = is_reply_to_bot(reply_to_obj, bot_user_id=self._bot_user_id or "")

        # Mention detection
        is_mention = is_mentioning_bot(raw_text, bot_display_name=self._bot_display_name)
        cleaned_text = clean_mention(raw_text, bot_display_name=self._bot_display_name)
        pseudo_mentions = [mention_name_for_zalo(m.strip()) for m in extract_target_mentions(raw_text) if m.strip()]

        is_group = str(chat_type).upper() == "GROUP"

        # Access Control: Check if group is allowed
        if settings.allowed_groups and str(chat_id) not in settings.allowed_groups:
            logger.warning(f"Ignored message from unauthorized chat_id: {chat_id}")
            return {"status": "forbidden", "chat_id": chat_id}

        # ------------------------------------------------------------------
        # Group-chat behavior: only respond when explicitly mentioned or when
        # the user is replying to a message the bot sent. Otherwise stay quiet
        # so the bot does not spam every group message.
        # ------------------------------------------------------------------
        if is_group and not is_mention and not is_reply_to_bot_msg:
            logger.info(f"Ignoring group message from {sender_name} because bot was not mentioned/replied to")
            return {"status": "ignored", "reason": "bot_not_addressed_in_group", "chat_id": chat_id}

        # If user sent an image without caption, provide a default natural prompt
        if photo_url and not str(raw_text).strip():
            cleaned_text = "Hãy xem và phân tích/mô tả chi tiết bức ảnh này giúp tôi."

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
                # Handle sticker command marker: [STICKER:<id>|<preview_url>]
                sticker_marker = re.match(r"^\[STICKER:([^|]+)\|([^\]]*)\]$", cmd_reply.strip())
                if sticker_marker:
                    sticker_id = sticker_marker.group(1)
                    preview_url = sticker_marker.group(2)
                    # sendSticker expects "sticker": "<pack_id>" exactly like the JS example.
                    sticker_result = zalo_client.send_sticker(str(chat_id), sticker_id)
                    if not sticker_result.get("ok"):
                        logger.warning(f"sendSticker failed ({sticker_result}), falling back to sendPhoto")
                        if preview_url:
                            zalo_client.send_photo(str(chat_id), preview_url, caption="")
                    return {"status": "command_processed", "chat_id": chat_id}

                # Handle image generation command marker: [IMAGE_GEN:<description>]
                image_marker = re.search(r"\[IMAGE_(?:AGY|GEN):([^\]]+)\]", cmd_reply.strip())
                if image_marker:
                    gen_description = image_marker.group(1).strip()
                    logger.info(f"Generating image from command: {gen_description}")
                    zalo_client.send_message(
                        chat_id=str(chat_id),
                        text="🎨 Đang tạo ảnh, vui lòng đợi một chút nhé...",
                        parse_mode="markdown"
                    )
                    try:
                        success, image_source = image_generation_service.generate_image(gen_description)
                        logger.info(f"Image generation result: success={success}, source={image_source[:120] if image_source else 'None'}")
                        if success:
                            logger.info(f"Calling send_photo for chat {chat_id} with source {image_source[:120]}")
                            photo_result = zalo_client.send_photo(str(chat_id), image_source, caption=gen_description)
                            logger.info(f"send_photo result: {photo_result}")
                            if not photo_result.get("ok"):
                                error_detail = photo_result.get("description", "unknown error")
                                zalo_client.send_message(
                                    chat_id=str(chat_id),
                                    text=f"❌ Không gửi được ảnh: {error_detail}",
                                    parse_mode="markdown"
                                )
                        else:
                            zalo_client.send_message(
                                chat_id=str(chat_id),
                                text=f"❌ Không tạo được ảnh: {image_source}",
                                parse_mode="markdown"
                            )
                    except Exception as e:
                        logger.exception(f"Error during image generation/send for command: {gen_description}")
                        zalo_client.send_message(
                            chat_id=str(chat_id),
                            text=f"❌ Lỗi khi gửi ảnh: {str(e)[:200]}",
                            parse_mode="markdown"
                        )
                    return {"status": "command_processed", "chat_id": chat_id}

                zalo_client.send_message(
                    chat_id=str(chat_id),
                    text=clean_markdown_for_zalo(cmd_reply),
                    parse_mode="markdown"
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
            "photo_url": photo_url,
            "reply_to_text": reply_to_text,
            "reply_to_sender": reply_to_sender,
            "is_reply_to_bot": is_reply_to_bot_msg,
            "is_mention": is_mention,
            "chat_type": chat_type,
            "pseudo_mentions": pseudo_mentions,
        }

        aggregator_service.enqueue_message(
            chat_id=str(chat_id),
            event_data=event_info,
            flush_callback=self._process_aggregated_batch
        )

        return {"status": "queued_for_debounce", "chat_id": chat_id}

    def _detect_quick_reply_intent(self, text: str) -> Optional[str]:
        """Return quick-reply category if the text is a simple greeting/thanks/bye."""
        text_lower = text.lower().strip()
        # Simple exact/prefix matches - keep lightweight
        if any(text_lower.startswith(w) for w in ["xin chào", "chào ", "chào", "hello", "hi ", "hi", "hey"]):
            return "hello"
        if any(text_lower.startswith(w) for w in ["cảm ơn", "cám ơn", "thank", "thanks", "tạ ơn"]):
            return "thanks"
        if any(text_lower.startswith(w) for w in ["tạm biệt", "bye", "goodbye", "bai"]):
            return "bye"
        return None

    def _process_aggregated_batch(self, chat_id: str, events: List[Dict[str, Any]]):
        """
        Executes after debounce timer expires.
        Gathers all consecutive texts and images into a single prompt, saving tokens & sending 1 unified response.
        """
        if not events:
            return

        latest_event = events[-1]
        user_id = latest_event["user_id"]
        sender_name = latest_event["sender_name"]
        event_type = latest_event["event_type"]

        # Extract photo URL if any message in the batch contained an image
        photo_url = next((e.get("photo_url") for e in reversed(events) if e.get("photo_url")), None)
        image_data = None
        if photo_url:
            logger.info(f"Downloading photo for Vision model: {photo_url[:100]}...")
            image_data = image_service.fetch_image_as_data_url(photo_url)

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

        # 1b. Fast-path: short greeting/thanks/bye replies without calling LLM
        if len(events) == 1 and not image_data and len(combined_cleaned_text) < 80:
            quick_category = self._detect_quick_reply_intent(combined_cleaned_text)
            if quick_category:
                self._send_quick_reply(chat_id, sender_name, quick_category)
                context_service.save_turn(str(chat_id), f"{sender_name}: {combined_cleaned_text}", self._quick_replies[quick_category][0].replace("{name}", sender_name or "bạn"), event_type=event_type)
                return

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
                    parse_mode="markdown"
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

        # 5. Format prompt with sender name (and any pseudo-mentions the user included)
        prompt_with_sender = f"{sender_name}: {combined_cleaned_text}" if sender_name else combined_cleaned_text
        if latest_event.get("is_reply_to_bot"):
            prompt_with_sender = f"[Người dùng đang trả lời tin nhắn của bot]\n{prompt_with_sender}"
        if latest_event.get("pseudo_mentions"):
            prompt_with_sender += f"\n[Các người dùng được đề cập trong câu hỏi: {', '.join(latest_event['pseudo_mentions'])}]"

        # 6. Send typing action while LLM is generating the reply
        zalo_client.send_chat_action(str(chat_id), "typing")

        # 7. Generate AI reply with Tri-Tier Context + Multimodal Vision
        raw_ai_reply = llm_service.generate_reply(
            prompt=prompt_with_sender,
            history=history,
            knowledge_base=knowledge_base,
            rolling_summary=rolling_summary,
            semantic_context=semantic_context,
            image_data=image_data,
            sender_name=sender_name
        )

        cleaned_ai_reply = strip_quota_badges(raw_ai_reply)
        reply_text = clean_markdown_for_zalo(cleaned_ai_reply)

        # 7. Web search for real-time information when the LLM admits it lacks data.
        #    We look for common refusal phrases and trigger DuckDuckGo search.
        if self._should_trigger_web_search(combined_cleaned_text, reply_text):
            try:
                search_results = web_search_service.search(combined_cleaned_text, max_results=5)
                if search_results:
                    web_search_context = self._format_search_results(search_results)
                    logger.info(f"Injecting web search context ({len(search_results)} results)")
                    raw_ai_reply = llm_service.generate_reply(
                        prompt=(
                            "Dựa vào kết quả tìm kiếm web dưới đây, hãy trả lời ngắn gọn cho câu hỏi:\n\n"
                            f"Câu hỏi: {combined_cleaned_text}\n\n"
                            f"{web_search_context}\n\n"
                            "Trả lời bằng tiếng Việt, ngắn gọn, chỉ dùng thông tin từ kết quả tìm kiếm."
                        ),
                        history=[],
                        knowledge_base="",
                        rolling_summary="",
                        semantic_context="",
                        image_data=None,
                        sender_name=sender_name,
                    )
                    cleaned_ai_reply = strip_quota_badges(raw_ai_reply)
                    reply_text = clean_markdown_for_zalo(cleaned_ai_reply)
            except Exception as e:
                logger.exception("Web search integration failed")

        # 7. Detect optional markers from LLM / command handler
        send_random_sticker = False
        gen_image_description = None

        if settings.STICKER_AUTO_SEND and "[STICKER_RANDOM]" in reply_text:
            reply_text = reply_text.replace("[STICKER_RANDOM]", "").strip()
            send_random_sticker = True

        image_match = re.search(r"\[IMAGE_(?:AGY|GEN):([^\]]+)\]", reply_text)
        if image_match:
            gen_image_description = image_match.group(1).strip()
            reply_text = reply_text.replace(image_match.group(0), "").strip()

        # 8. Append transient quota badge if applicable
        final_send_text = f"{reply_text}{quota_badge}" if quota_badge else reply_text

        # 9. Send unified message back to Zalo as rich text (markdown).
        #    Zalo Bot Platform does NOT support reply_to_message_id from bots,
        #    so we no longer send that field.
        zalo_client.send_message(
            chat_id=str(chat_id),
            text=final_send_text,
            parse_mode="markdown"
        )

        # 9b. Send optional random sticker after text
        if send_random_sticker:
            sticker_item = sticker_service.get_random_sticker()
            if sticker_item:
                sticker_id, preview_url = sticker_item
                logger.info(f"Sending random sticker after reply: {sticker_id}")
                zalo_client.send_sticker(str(chat_id), sticker_id)

        # 9c. Generate and send image requested via /image command
        if gen_image_description:
            logger.info(f"Generating image: {gen_image_description}")
            zalo_client.send_message(
                chat_id=str(chat_id),
                text="🎨 Đang tạo ảnh, vui lòng đợi một chút nhé...",
                parse_mode="markdown"
            )
            try:
                success, image_source = image_generation_service.generate_image(gen_image_description)
                logger.info(f"Image generation result: success={success}, source={image_source[:120] if image_source else 'None'}")
                if success:
                    logger.info(f"Calling send_photo for chat {chat_id} with source {image_source[:120]}")
                    photo_result = zalo_client.send_photo(str(chat_id), image_source, caption=gen_image_description)
                    logger.info(f"send_photo result: {photo_result}")
                    if not photo_result.get("ok"):
                        error_detail = photo_result.get("description", "unknown error")
                        zalo_client.send_message(
                            chat_id=str(chat_id),
                            text=f"❌ Không gửi được ảnh: {error_detail}",
                            parse_mode="markdown"
                        )
                else:
                    zalo_client.send_message(
                        chat_id=str(chat_id),
                        text=f"❌ Không tạo được ảnh: {image_source}",
                        parse_mode="markdown"
                    )
            except Exception as e:
                logger.exception(f"Error during image generation/send: {gen_image_description}")
                zalo_client.send_message(
                    chat_id=str(chat_id),
                    text=f"❌ Lỗi khi gửi ảnh: {str(e)[:200]}",
                    parse_mode="markdown"
                )

        # 10. Save turn to conversation database
        saved_msg = f"{sender_name}: [Hình ảnh] {combined_cleaned_text}" if image_data else (f"{sender_name}: {combined_cleaned_text}" if sender_name else combined_cleaned_text)
        context_service.save_turn(str(chat_id), saved_msg, reply_text, event_type=event_type)

        # 10. Check & rollup summary in background (Episodic Memory compaction)
        context_service.trigger_async_summary_update(str(chat_id))

    @staticmethod
    def _should_trigger_web_search(query: str, reply: str) -> bool:
        """
        Decide whether the bot should perform a web search based on the user's
        question and the LLM's reply.  We search when the LLM appears to lack
        current/real-world knowledge or refuses to answer.
        """
        query_lower = query.lower()
        reply_lower = reply.lower()

        # Direct signals that the LLM cannot answer.
        refusal_phrases = [
            "không có chiêu search web",
            "không có khả năng",
            "không thể truy cập",
            "không có thông tin",
            "không có dữ liệu",
            "không biết",
            "tôi không biết",
            "em không biết",
            "mình không biết",
            "tôi không chắc",
            "em không chắc",
            "tự lên google",
            "tự lên trang web",
            "kiến thức đến ngày",
            "kiến thức có hạn",
            "không được kết nối internet",
            "không có internet",
        ]
        if any(p in reply_lower for p in refusal_phrases):
            return True

        # Keywords suggesting the user wants fresh/external facts.
        realtime_keywords = [
            "thời tiết", "dự báo thời tiết",
            "tỷ giá", "giá vàng", "giá xăng", "giá bitcoin", "giá coin",
            "lịch thi đấu", "kết quả bóng đá", "tỷ số",
            "tin tức", "tin mới", "tin nóng", "sự kiện",
            "hôm nay", "ngày mai", "hiện tại", "bây giờ", "mới nhất",
            "chứng khoán", "thị trường", "ngoại tệ", "lãi suất",
        ]
        if any(k in query_lower for k in realtime_keywords):
            return True

        return False

    @staticmethod
    def _format_search_results(results: list) -> str:
        """Format DuckDuckGo results into a concise context string."""
        lines = ["Kết quả tìm kiếm web:"]
        for idx, r in enumerate(results, 1):
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            lines.append(f"{idx}. {title}: {snippet}")
        return "\n".join(lines)


message_handler = MessageHandler()
