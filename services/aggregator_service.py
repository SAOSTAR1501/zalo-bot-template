import logging
import threading
from typing import Dict, List, Any, Callable
from config.settings import settings

logger = logging.getLogger(__name__)


class MessageAggregator:
    """
    Asynchronous Debounced Message Aggregator.
    Gathers rapid consecutive messages from a user/group into a single batch
    before triggering LLM processing, avoiding fragmented replies and saving tokens.
    """

    def __init__(self, debounce_seconds: float = settings.DEBOUNCE_WAIT_SECONDS):
        self.debounce_seconds = debounce_seconds
        self.buffers: Dict[str, List[Dict[str, Any]]] = {}
        self.timers: Dict[str, threading.Timer] = {}
        self.locks: Dict[str, threading.Lock] = {}
        self.global_lock = threading.Lock()

    def enqueue_message(
        self,
        chat_id: str,
        event_data: Dict[str, Any],
        flush_callback: Callable[[str, List[Dict[str, Any]]], None]
    ):
        """
        Appends message to chat buffer and resets debounce timer.
        """
        with self.global_lock:
            if chat_id not in self.locks:
                self.locks[chat_id] = threading.Lock()
            if chat_id not in self.buffers:
                self.buffers[chat_id] = []

        with self.locks[chat_id]:
            # Cancel active debounce timer
            if chat_id in self.timers:
                try:
                    self.timers[chat_id].cancel()
                except Exception:
                    pass

            self.buffers[chat_id].append(event_data)
            count = len(self.buffers[chat_id])
            logger.info(f"Queued message {count} for chat {chat_id} (debounce: {self.debounce_seconds}s)")

            # Start new debounce timer
            timer = threading.Timer(
                self.debounce_seconds,
                self._flush_buffer,
                args=(chat_id, flush_callback)
            )
            self.timers[chat_id] = timer
            timer.daemon = True
            timer.start()

    def _flush_buffer(
        self,
        chat_id: str,
        flush_callback: Callable[[str, List[Dict[str, Any]]], None]
    ):
        """
        Fires when debounce timer expires. Pulls all buffered messages and executes callback.
        """
        with self.locks[chat_id]:
            events = self.buffers.pop(chat_id, [])

        if events:
            logger.info(f"Debounce timer expired for chat {chat_id}. Processing batch of {len(events)} messages.")
            try:
                flush_callback(chat_id, events)
            except Exception as e:
                logger.error(f"Error executing debounce flush callback for {chat_id}: {e}")


aggregator_service = MessageAggregator()
