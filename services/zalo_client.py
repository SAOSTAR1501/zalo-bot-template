import logging
import requests
from typing import Dict, Any, Optional
from config.settings import settings

logger = logging.getLogger(__name__)


class ZaloBotClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.ZALO_BOT_TOKEN
        self.base_url = "https://bot-api.zaloplatforms.com"

    def _url(self, method: str) -> str:
        return f"{self.base_url}/bot{self.token}/{method}"

    def get_me(self) -> Dict[str, Any]:
        """Get Bot information."""
        url = self._url("getMe")
        try:
            r = requests.post(url, timeout=15)
            return r.json()
        except Exception as e:
            logger.error(f"Failed to getMe: {e}")
            return {"ok": False, "error": str(e)}

    def get_webhook_info(self) -> Dict[str, Any]:
        """Get current webhook status."""
        url = self._url("getWebhookInfo")
        try:
            r = requests.post(url, timeout=15)
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
            r = requests.post(endpoint, json=payload, timeout=20)
            return r.json()
        except Exception as e:
            logger.error(f"Failed to setWebhook: {e}")
            return {"ok": False, "error": str(e)}

    def delete_webhook(self) -> Dict[str, Any]:
        """Remove webhook configuration."""
        url = self._url("deleteWebhook")
        try:
            r = requests.post(url, timeout=15)
            return r.json()
        except Exception as e:
            logger.error(f"Failed to deleteWebhook: {e}")
            return {"ok": False, "error": str(e)}

    def send_message(self, chat_id: str, text: str) -> Dict[str, Any]:
        """Send plain text message to a user or group."""
        if not self.token:
            logger.error("ZALO_BOT_TOKEN is not configured")
            return {"ok": False, "error": "Missing token"}

        url = self._url("sendMessage")
        payload = {
            "chat_id": str(chat_id),
            "text": text[:2000]
        }
        try:
            r = requests.post(url, json=payload, timeout=20)
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
            r = requests.post(url, json=payload, timeout=20)
            return r.json()
        except Exception as e:
            logger.error(f"Failed to sendPhoto: {e}")
            return {"ok": False, "error": str(e)}


zalo_client = ZaloBotClient()
