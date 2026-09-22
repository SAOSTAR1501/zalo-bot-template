import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, Optional
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
            total=3,
            backoff_factor=0.3,
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

    def _url(self, method: str) -> str:
        return f"{self.base_url}/bot{self.token}/{method}"

    def get_me(self) -> Dict[str, Any]:
        """Get Bot information."""
        url = self._url("getMe")
        try:
            r = self.session.post(url, timeout=(5, 15))
            return r.json()
        except Exception as e:
            logger.error(f"Failed to getMe: {e}")
            return {"ok": False, "error": str(e)}

    def get_webhook_info(self) -> Dict[str, Any]:
        """Get current webhook status."""
        url = self._url("getWebhookInfo")
        try:
            r = self.session.post(url, timeout=(5, 15))
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
            r = self.session.post(endpoint, json=payload, timeout=(5, 20))
            return r.json()
        except Exception as e:
            logger.error(f"Failed to setWebhook: {e}")
            return {"ok": False, "error": str(e)}

    def delete_webhook(self) -> Dict[str, Any]:
        """Remove webhook configuration."""
        url = self._url("deleteWebhook")
        try:
            r = self.session.post(url, timeout=(5, 15))
            return r.json()
        except Exception as e:
            logger.error(f"Failed to deleteWebhook: {e}")
            return {"ok": False, "error": str(e)}

    def send_message(self, chat_id: str, text: str, reply_to_message_id: Optional[str] = None) -> Dict[str, Any]:
        """Send plain text message to a user or group, optionally replying to / quoting a specific message."""
        if not self.token:
            logger.error("ZALO_BOT_TOKEN is not configured")
            return {"ok": False, "error": "Missing token"}

        url = self._url("sendMessage")
        payload = {
            "chat_id": str(chat_id),
            "text": text[:2000]
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = str(reply_to_message_id)

        try:
            r = self.session.post(url, json=payload, timeout=(10, 25))
            logger.info(f"Zalo send response ({r.status_code}): {r.text[:300]}")
            return r.json() if r.text else {"status_code": r.status_code}
        except Exception as e:
            logger.error(f"Failed to sendMessage: {e}")
            return {"ok": False, "error": str(e)}

    def send_photo(self, chat_id: str, photo_url: str, caption: Optional[str] = None) -> Dict[str, Any]:
        """Send photo by URL."""
        url = self._url("sendPhoto")
        payload = {
            "chat_id": str(chat_id),
            "photo": photo_url
        }
        if caption:
            payload["caption"] = caption[:1024]
        try:
            r = self.session.post(url, json=payload, timeout=(10, 25))
            return r.json()
        except Exception as e:
            logger.error(f"Failed to sendPhoto: {e}")
            return {"ok": False, "error": str(e)}


zalo_client = ZaloBotClient()

