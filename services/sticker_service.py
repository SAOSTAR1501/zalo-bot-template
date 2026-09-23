import logging
import random
import re
from typing import Optional, List, Dict
from config.settings import settings

logger = logging.getLogger(__name__)


# Default sticker catalog using widely-known Zalo sticker CDN URLs.
# Each entry maps a sentiment/keyword to one or more sticker image URLs.
# You can override the whole catalog via the STICKER_CATALOG_JSON env var
# or add more URLs via STICKER_EXTRA_URLS.
DEFAULT_STICKER_CATALOG: Dict[str, List[str]] = {
    "hello": [
        "https://zalo-api.zadn.vn/1/0/0/5/s1/455/0/7/455007880455.png",
        "https://zalo-api.zadn.vn/1/0/0/3/s1/421/1/7/421017880421.png",
    ],
    "thanks": [
        "https://zalo-api.zadn.vn/1/0/0/1/s1/461/0/6/461006880461.png",
        "https://zalo-api.zadn.vn/1/0/0/9/s1/434/1/7/434017880434.png",
    ],
    "sorry": [
        "https://zalo-api.zadn.vn/1/0/0/1/s1/432/0/4/432004880432.png",
        "https://zalo-api.zadn.vn/1/0/0/3/s1/445/1/1/445011880445.png",
    ],
    "laugh": [
        "https://zalo-api.zadn.vn/1/0/0/8/s1/431/1/9/431019880431.png",
        "https://zalo-api.zadn.vn/1/0/0/4/s1/463/0/0/463000880463.png",
    ],
    "love": [
        "https://zalo-api.zadn.vn/1/0/0/0/s1/430/0/8/430008880430.png",
        "https://zalo-api.zadn.vn/1/0/0/6/s1/436/1/6/436016880436.png",
    ],
    "cry": [
        "https://zalo-api.zadn.vn/1/0/0/2/s1/438/0/6/438006880438.png",
        "https://zalo-api.zadn.vn/1/0/0/8/s1/442/0/2/442002880442.png",
    ],
    "angry": [
        "https://zalo-api.zadn.vn/1/0/0/5/s1/440/0/1/440001880440.png",
        "https://zalo-api.zadn.vn/1/0/0/7/s1/448/1/2/448012880448.png",
    ],
    "ok": [
        "https://zalo-api.zadn.vn/1/0/0/9/s1/439/0/5/439005880439.png",
        "https://zalo-api.zadn.vn/1/0/0/1/s1/446/0/4/446004880446.png",
    ],
    "goodnight": [
        "https://zalo-api.zadn.vn/1/0/0/4/s1/449/0/7/449007880449.png",
    ],
    "goodmorning": [
        "https://zalo-api.zadn.vn/1/0/0/2/s1/450/0/9/450009880450.png",
    ],
    "bye": [
        "https://zalo-api.zadn.vn/1/0/0/8/s1/451/0/3/451003880451.png",
    ],
    "congrats": [
        "https://zalo-api.zadn.vn/1/0/0/6/s1/452/0/0/452000880452.png",
    ],
    "motivation": [
        "https://zalo-api.zadn.vn/1/0/0/0/s1/454/0/8/454008880454.png",
    ],
}


class StickerService:
    def __init__(self):
        self.catalog: Dict[str, List[str]] = self._load_catalog()

    def _load_catalog(self) -> Dict[str, List[str]]:
        """Load sticker catalog from settings or use the default set."""
        import json
        catalog: Dict[str, List[str]] = {}
        if settings.STICKER_CATALOG_JSON:
            try:
                catalog = json.loads(settings.STICKER_CATALOG_JSON)
                logger.info("Loaded custom sticker catalog from STICKER_CATALOG_JSON")
            except Exception as e:
                logger.warning(f"Invalid STICKER_CATALOG_JSON, falling back to default: {e}")

        if not catalog:
            catalog = DEFAULT_STICKER_CATALOG.copy()

        # Merge extra sticker URLs keyed by category, e.g. "laugh: url1, url2 | cry: url3"
        if settings.STICKER_EXTRA_URLS:
            for segment in settings.STICKER_EXTRA_URLS.split("|"):
                if ":" not in segment:
                    continue
                key, urls = segment.split(":", 1)
                key = key.strip().lower()
                catalog.setdefault(key, []).extend([u.strip() for u in urls.split(",") if u.strip()])

        return catalog

    @property
    def available_tags(self) -> List[str]:
        return sorted(self.catalog.keys())

    def get_sticker(self, tag: str) -> Optional[str]:
        """Return a random sticker URL for the given tag, or None if unknown."""
        tag = tag.lower().strip()
        urls = self.catalog.get(tag)
        if not urls:
            return None
        return random.choice(urls)

    def pick_sticker_for_text(self, text: str) -> Optional[str]:
        """
        Naive keyword-based sticker picker. Looks for known sentiment keywords
        in the supplied text (e.g. an AI reply) and returns a matching sticker.
        """
        if not text:
            return None
        text_lower = text.lower()

        # Exact phrase priority
        priority_map = {
            "xin chào": "hello",
            "chào buổi sáng": "goodmorning",
            "buổi sáng": "goodmorning",
            "chào buổi tối": "goodnight",
            "chúc ngủ ngon": "goodnight",
            "ngủ ngon": "goodnight",
            "cảm ơn": "thanks",
            "thank": "thanks",
            "xin lỗi": "sorry",
            "tạm biệt": "bye",
            "bye": "bye",
            "chúc mừng": "congrats",
            "giỏi quá": "congrats",
            "cố lên": "motivation",
        }
        for phrase, tag in priority_map.items():
            if phrase in text_lower:
                return self.get_sticker(tag)

        # Keyword regex matching
        keyword_map = {
            r"\b(haha|hihi|hehe|cười|funny|laugh|😂|🤣)\b": "laugh",
            r"\b(yêu|love|thương|❤️|💕|😍)\b": "love",
            r"\b(khóc|buồn|cry|sad|😢|😭)\b": "cry",
            r"\b(giận|tức|angry|annoyed|😡|🤬)\b": "angry",
            r"\b(ok|oke|đồng ý|agree|yes|👌|👍)\b": "ok",
        }
        for pattern, tag in keyword_map.items():
            if re.search(pattern, text_lower):
                return self.get_sticker(tag)

        return None

    def list_catalog(self) -> str:
        lines = ["🎨 KHO STICKER CỦA BOT:"]
        for tag, urls in sorted(self.catalog.items()):
            lines.append(f"• {tag}: {len(urls)} sticker(s)")
        lines.append("\nGõ /sticker <tên> để bot gửi thử. Ví dụ: /sticker laugh")
        return "\n".join(lines)


sticker_service = StickerService()
