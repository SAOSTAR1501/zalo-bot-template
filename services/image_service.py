import base64
import logging
import requests
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class ImageService:
    @staticmethod
    def fetch_image_as_data_url(image_url: str, timeout: int = 15) -> Optional[str]:
        """
        Downloads image from given URL and converts it to base64 data URL.
        Example: data:image/jpeg;base64,/9j/4AAQSkZJRgABA...
        """
        if not image_url:
            return None

        # Already a data URL
        if image_url.startswith("data:image/"):
            return image_url

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(image_url, headers=headers, timeout=timeout)
            if resp.status_code == 200 and resp.content:
                content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                if not content_type.startswith("image/"):
                    content_type = "image/jpeg"
                b64_data = base64.b64encode(resp.content).decode("utf-8")
                return f"data:{content_type};base64,{b64_data}"
            else:
                logger.warning(f"Failed to download image from {image_url}: HTTP {resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching image from {image_url}: {e}")
            return None


image_service = ImageService()
