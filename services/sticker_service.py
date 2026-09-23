import logging
import random
import re
import requests
import json
from typing import Optional, List, Dict
from config.settings import settings

logger = logging.getLogger(__name__)


# Sentiment keywords used to map a sticker pack name to a mood/category.
SENTIMENT_KEYWORDS: Dict[str, List[str]] = {
    "hello": ["chào", "xin chào", "hello", "hi", "morning", "buổi sáng", "buổi tối"],
    "thanks": ["cảm ơn", "thank", "cám ơn", "tạ ơn"],
    "sorry": ["xin lỗi", "lỗi", "sorry", "xin thứ lỗi"],
    "laugh": ["cười", "haha", "hihi", "hehe", "vui", "hài", "cười xỉu", "funny", "laugh"],
    "love": ["yêu", "love", "thương", "tim", "crush", "iu", "thương quá"],
    "cry": ["khóc", "buồn", "cry", "sad", "mếu", "tủi thân"],
    "angry": ["giận", "tức", "angry", "bực", "cáu", "khó chịu"],
    "ok": ["ok", "oke", "đồng ý", "được", "yes", "ừ", "vâng", "dạ"],
    "goodnight": ["ngủ ngon", "goodnight", "đêm", "ngủ"],
    "goodmorning": ["buổi sáng", "sáng", "good morning"],
    "bye": ["tạm biệt", "bye", "see you", "bai"],
    "congrats": ["chúc mừng", "congrats", "giỏi", "tuyệt", "hay", "xuất sắc"],
    "motivation": ["cố lên", "đừng bỏ cuộc", "fighting", "cố gắng"],
}


class StickerService:
    """
    Sticker picker for Zalo Bot.

    Zalo Bot Platform's sendSticker API accepts a sticker URL.  The official
    sticker store (https://stickers.zaloapp.com) exposes a public endpoint that
    lists available sticker packs.  We use the pack-level preview / icon URLs
    as the sticker asset.  If sendSticker is rejected, the caller can fall back
    to sendPhoto with the same URL.
    """

    def __init__(self):
        self._catalog: Optional[Dict[str, List[str]]] = None
        self._last_fetch_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def available_tags(self) -> List[str]:
        return sorted(self._get_catalog().keys())

    def get_sticker(self, tag: str) -> Optional[str]:
        """Return a random sticker URL for the given tag, or None if unknown."""
        tag = tag.lower().strip()
        urls = self._get_catalog().get(tag)
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
            r"\b(haha|hihi|hehe|cười|vui|hài|funny|laugh|😂|🤣)\b": "laugh",
            r"\b(yêu|love|thương|❤️|💕|😍)\b": "love",
            r"\b(khóc|buồn|cry|sad|😢|😭)\b": "cry",
            r"\b(giận|tức|angry|annoyed|bực|cáu|😡|🤬)\b": "angry",
            r"\b(ok|oke|đồng ý|được|yes|👌|👍)\b": "ok",
        }
        for pattern, tag in keyword_map.items():
            if re.search(pattern, text_lower):
                return self.get_sticker(tag)

        return None

    def list_catalog(self) -> str:
        lines = ["🎨 KHO STICKER CỦA BOT:"]
        for tag, urls in sorted(self._get_catalog().items()):
            lines.append(f"• {tag}: {len(urls)} sticker(s)")
        if self._last_fetch_error:
            lines.append(f"\n⚠️ Lưu ý: đang dùng sticker mặc định do lỗi fetch ({self._last_fetch_error}).")
        lines.append("\nGõ /sticker <tên> để bot gửi thử. Ví dụ: /sticker laugh")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_catalog(self) -> Dict[str, List[str]]:
        """Lazy-load sticker catalog from Zalo sticker store or env overrides."""
        if self._catalog is not None:
            return self._catalog

        # 1. Env override wins.
        if settings.STICKER_CATALOG_JSON:
            try:
                self._catalog = json.loads(settings.STICKER_CATALOG_JSON)
                logger.info("Loaded custom sticker catalog from STICKER_CATALOG_JSON")
                return self._catalog
            except Exception as e:
                logger.warning(f"Invalid STICKER_CATALOG_JSON, falling back: {e}")

        # 2. Try fetching live from Zalo sticker store.
        live_catalog = self._fetch_zalo_sticker_catalog()
        if live_catalog:
            self._catalog = live_catalog
            return self._catalog

        # 3. Fallback to a small built-in set of verified public URLs.
        self._catalog = self._default_catalog()
        return self._catalog

    def _fetch_zalo_sticker_catalog(self) -> Optional[Dict[str, List[str]]]:
        """Fetch sticker packs from https://stickers.zaloapp.com/sticker and map to sentiments."""
        try:
            r = requests.get(
                "https://stickers.zaloapp.com/sticker",
                timeout=(5, 15),
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json",
                },
            )
            if r.status_code != 200:
                self._last_fetch_error = f"HTTP {r.status_code}"
                return None

            data = r.json()
            packs = data.get("value", {}).get("all", [])
            if not packs:
                self._last_fetch_error = "empty pack list"
                return None

            catalog: Dict[str, List[str]] = {tag: [] for tag in SENTIMENT_KEYWORDS.keys()}
            seen_urls: set = set()

            for pack in packs:
                name = (pack.get("name") or "").lower()
                # Prefer preview image, fallback to icon.
                url = pack.get("thumbImg") or pack.get("iconUrl") or ""
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                for tag, keywords in SENTIMENT_KEYWORDS.items():
                    if any(kw in name for kw in keywords):
                        catalog[tag].append(url)
                        break  # one pack belongs to first matching sentiment only

            # Drop empty categories.
            catalog = {k: v for k, v in catalog.items() if v}

            if not catalog:
                self._last_fetch_error = "no sentiment mapping"
                return None

            logger.info(f"Loaded {sum(len(v) for v in catalog.values())} sticker URLs from Zalo store")
            self._last_fetch_error = None
            return catalog

        except Exception as e:
            self._last_fetch_error = str(e)
            logger.warning(f"Failed to fetch Zalo sticker catalog: {e}")
            return None

    def _default_catalog(self) -> Dict[str, List[str]]:
        """A minimal fallback catalog with known-working public Zalo sticker URLs."""
        return {
            "hello": ["https://zalo-api.zadn.vn/e/7/3/5/1/12658/preview/440x440.png"],
            "laugh": ["https://zalo-api.zadn.vn/e/7/3/5/1/12658/preview/440x440.png"],
            "love": ["https://zalo-api.zadn.vn/2/3/6/5/2/10590/preview/love_cover.png"],
            "cry": ["https://zalo-api.zadn.vn/d/2/a/9/a/12003/preview/440x440.png"],
            "ok": ["https://zalo-api.zadn.vn/9/b/2/3/2/12628/preview/440x440.png"],
            "bye": ["https://zalo-api.zadn.vn/8/8/9/b/8/12738/preview/440x440.png"],
            "congrats": ["https://zalo-api.zadn.vn/5/a/5/f/a/12689/preview/440x440.png"],
        }


sticker_service = StickerService()
