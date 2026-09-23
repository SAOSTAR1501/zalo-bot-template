import logging
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, Optional, List
from config.settings import settings

logger = logging.getLogger(__name__)


class ZaloBotClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.ZALO_BOT_TOKEN
        self.base_url = "https://bot-api.zaloplatforms.com"
        self._init_session()

    def _init_session(self):
        """Initializes a persistent HTTP session with connection pooling and auto-retries."""
        self.session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=1.0,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=retries
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    @staticmethod
    def _api_timeout(connect: int = 10, read: int = 25) -> tuple:
        """Return a safe timeout tuple for Zalo API calls."""
        return (connect, read)

    def _url(self, method: str) -> str:
        return f"{self.base_url}/bot{self.token}/{method}"

    def get_me(self) -> Dict[str, Any]:
        """Get Bot information."""
        url = self._url("getMe")
        try:
            r = self.session.post(url, timeout=self._api_timeout(connect=15, read=20))
            return r.json()
        except Exception as e:
            logger.error(f"Failed to getMe: {e}")
            return {"ok": False, "error": str(e)}

    def get_webhook_info(self) -> Dict[str, Any]:
        """Get current webhook status."""
        url = self._url("getWebhookInfo")
        try:
            r = self.session.post(url, timeout=self._api_timeout(connect=15, read=20))
            return r.json()
        except Exception as e:
            logger.error(f"Failed to getWebhookInfo: {e}")
            return {"ok": False, "error": str(e)}

    def set_webhook(self, url: str, secret_token: str) -> Dict[str, Any]:
        """Set webhook URL with secret token."""
        endpoint = self._url("setWebhook")
        payload = {
            "url": url,
            "secret_token": secret_token
        }
        try:
            r = self.session.post(endpoint, json=payload, timeout=self._api_timeout(connect=15, read=30))
            return r.json()
        except Exception as e:
            logger.error(f"Failed to setWebhook: {e}")
            return {"ok": False, "error": str(e)}

    def delete_webhook(self) -> Dict[str, Any]:
        """Remove webhook configuration."""
        url = self._url("deleteWebhook")
        try:
            r = self.session.post(url, timeout=self._api_timeout(connect=15, read=20))
            return r.json()
        except Exception as e:
            logger.error(f"Failed to deleteWebhook: {e}")
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Rich text helpers matching Zalo Bot Platform official docs
    # ------------------------------------------------------------------
    @staticmethod
    def make_text_styles_bold(text: str) -> List[Dict[str, Any]]:
        """Return a single bold style run covering the whole text (UTF-16 offsets)."""
        # Zalo text_styles offsets are UTF-16 code units like JavaScript.
        # For the common case where text has no surrogate pairs, len(text) is fine.
        return [{"start": 0, "len": len(text), "st": ["b"]}]

    @staticmethod
    def make_text_styles_mention(display_name: str) -> List[Dict[str, Any]]:
        """Style run that looks like a mention (blue/default color). Not a real mention."""
        return [{"start": 0, "len": len(display_name), "st": ["c_050a19"]}]

    # ------------------------------------------------------------------
    # Send API methods
    # ------------------------------------------------------------------
    def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: Optional[str] = None,
        text_styles: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Send plain/rich text message to a user or group.

        Official Zalo sendMessage parameters:
          - chat_id (required)
          - text (required, 1-2000 chars)
          - parse_mode (optional): 'markdown' or 'html'
          - text_styles (optional): array of style runs. If parse_mode is set,
            text_styles is ignored by Zalo.
        """
        if not self.token:
            logger.error("ZALO_BOT_TOKEN is not configured")
            return {"ok": False, "error": "Missing token"}

        url = self._url("sendMessage")
        payload: Dict[str, Any] = {
            "chat_id": str(chat_id),
            "text": text[:2000]
        }

        if parse_mode:
            payload["parse_mode"] = parse_mode
        elif text_styles:
            payload["text_styles"] = text_styles

        try:
            r = self.session.post(url, json=payload, timeout=(10, 25))
            logger.info(f"Zalo send response ({r.status_code}): {r.text[:300]}")
            return r.json() if r.text else {"status_code": r.status_code}
        except Exception as e:
            logger.error(f"Failed to sendMessage: {e}")
            return {"ok": False, "error": str(e)}

    def send_photo(
        self,
        chat_id: str,
        photo_url: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send photo by URL or local file path with optional caption."""
        url = self._url("sendPhoto")
        payload: Dict[str, Any] = {
            "chat_id": str(chat_id),
        }
        if caption:
            payload["caption"] = caption[:2000]
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            # Local file path: upload via multipart/form-data
            if os.path.isfile(photo_url):
                with open(photo_url, "rb") as f:
                    files = {"photo": f}
                    r = self.session.post(url, data=payload, files=files, timeout=(15, 60))
            else:
                payload["photo"] = photo_url
                r = self.session.post(url, json=payload, timeout=(10, 25))
            return r.json()
        except Exception as e:
            logger.error(f"Failed to sendPhoto: {e}")
            return {"ok": False, "error": str(e)}

    def send_sticker(self, chat_id: str, sticker_url: str) -> Dict[str, Any]:
        """Send a sticker by URL (must come from https://stickers.zaloapp.com/)."""
        url = self._url("sendSticker")
        payload = {
            "chat_id": str(chat_id),
            "sticker": sticker_url
        }
        try:
            r = self.session.post(url, json=payload, timeout=(10, 25))
            return r.json()
        except Exception as e:
            logger.error(f"Failed to sendSticker: {e}")
            return {"ok": False, "error": str(e)}

    def send_voice(self, chat_id: str, voice_url: str) -> Dict[str, Any]:
        """
        Send a voice message (.aac) to a private chat only.
        sendVoice does NOT support groups per Zalo docs.
        """
        url = self._url("sendVoice")
        payload = {
            "chat_id": str(chat_id),
            "voice_url": voice_url
        }
        try:
            r = self.session.post(url, json=payload, timeout=(10, 25))
            return r.json()
        except Exception as e:
            logger.error(f"Failed to sendVoice: {e}")
            return {"ok": False, "error": str(e)}

    def send_chat_action(self, chat_id: str, action: str = "typing") -> Dict[str, Any]:
        """Display a temporary chat action (typing, upload_photo)."""
        url = self._url("sendChatAction")
        payload = {
            "chat_id": str(chat_id),
            "action": action
        }
        try:
            r = self.session.post(url, json=payload, timeout=(5, 15))
            return r.json()
        except Exception as e:
            logger.error(f"Failed to sendChatAction: {e}")
            return {"ok": False, "error": str(e)}


zalo_client = ZaloBotClient()
