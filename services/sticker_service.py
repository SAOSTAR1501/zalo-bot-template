import logging
import random
import re
import requests
import json
from typing import Optional, List, Dict, Tuple
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

    Zalo Bot Platform's sendSticker API accepts a sticker reference from
    https://stickers.zaloapp.com.  The public sticker store endpoint lists
    packs, each with an opaque pack id.  We send that pack id via sendSticker
    and fall back to sending the pack preview image via sendPhoto if Zalo
    rejects the id.
    """

    def __init__(self):
        self._catalog: Optional[Dict[str, List[Tuple[str, str]]]] = None
        self._last_fetch_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def available_tags(self) -> List[str]:
        return sorted(self._get_catalog().keys())

    def get_sticker(self, tag: str) -> Optional[Tuple[str, str]]:
        """
        Return a random (sticker_id, preview_url) tuple for the given tag,
        or None if unknown.
        """
        tag = tag.lower().strip()
        items = self._get_catalog().get(tag)
        if not items:
            return None
        return random.choice(items)

    def pick_sticker_for_text(self, text: str) -> Optional[Tuple[str, str]]:
        """
        Naive keyword-based sticker picker. Returns (sticker_id, preview_url)
        for the first sentiment matched in the text.
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
        for tag, items in sorted(self._get_catalog().items()):
            lines.append(f"• {tag}: {len(items)} bộ sticker")
        if self._last_fetch_error:
            lines.append(f"\n⚠️ Lưu ý: đang dùng sticker mặc định do lỗi fetch ({self._last_fetch_error}).")
        lines.append("\nGõ /sticker <tên> để bot gửi thử. Ví dụ: /sticker laugh")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_catalog(self) -> Dict[str, List[Tuple[str, str]]]:
        """Lazy-load sticker catalog from Zalo sticker store or env overrides."""
        if self._catalog is not None:
            return self._catalog

        # 1. Env override wins.
        if settings.STICKER_CATALOG_JSON:
            try:
                raw = json.loads(settings.STICKER_CATALOG_JSON)
                # Convert simple URL lists to (id, url) tuples.
                catalog: Dict[str, List[Tuple[str, str]]] = {}
                for tag, entries in raw.items():
                    catalog[tag] = []
                    for entry in entries:
                        if isinstance(entry, dict):
                            catalog[tag].append((entry.get("id", ""), entry.get("url", "")))
                        elif isinstance(entry, str):
                            catalog[tag].append((entry, entry))
                logger.info("Loaded custom sticker catalog from STICKER_CATALOG_JSON")
                self._catalog = catalog
                return self._catalog
            except Exception as e:
                logger.warning(f"Invalid STICKER_CATALOG_JSON, falling back: {e}")

        # 2. Try fetching live from Zalo sticker store.
        live_catalog = self._fetch_zalo_sticker_catalog()
        if live_catalog:
            self._catalog = live_catalog
            return self._catalog

        # 3. Fallback to a small built-in set.
        self._catalog = self._default_catalog()
        return self._catalog

    def _fetch_zalo_sticker_catalog(self) -> Optional[Dict[str, List[Tuple[str, str]]]]:
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

            catalog: Dict[str, List[Tuple[str, str]]] = {tag: [] for tag in SENTIMENT_KEYWORDS.keys()}
            seen_ids: set = set()

            for pack in packs:
                pack_id = pack.get("id", "")
                name = (pack.get("name") or "").lower()
                preview_url = pack.get("thumbImg") or pack.get("iconUrl") or ""
                if not pack_id or pack_id in seen_ids:
                    continue
                seen_ids.add(pack_id)

                for tag, keywords in SENTIMENT_KEYWORDS.items():
                    if any(kw in name for kw in keywords):
                        catalog[tag].append((pack_id, preview_url))
                        break  # one pack belongs to first matching sentiment only

            # Drop empty categories.
            catalog = {k: v for k, v in catalog.items() if v}

            if not catalog:
                self._last_fetch_error = "no sentiment mapping"
                return None

            logger.info(f"Loaded {sum(len(v) for v in catalog.values())} sticker packs from Zalo store")
            self._last_fetch_error = None
            return catalog

        except Exception as e:
            self._last_fetch_error = str(e)
            logger.warning(f"Failed to fetch Zalo sticker catalog: {e}")
            return None

    def _default_catalog(self) -> Dict[str, List[Tuple[str, str]]]:
        """A minimal fallback catalog with known public pack ids / preview URLs."""
        return {
            "hello": [("34c1ca1af65f1f01464e", "https://zalo-api.zadn.vn/e/7/3/5/1/12658/preview/440x440.png")],
            "laugh": [("34c1ca1af65f1f01464e", "https://zalo-api.zadn.vn/e/7/3/5/1/12658/preview/440x440.png")],
            "love": [("bf596d9a51dfb881e1ce", "https://zalo-api.zadn.vn/2/3/6/5/2/10590/preview/love_cover.png")],
            "cry": [("e5c88a0cb6495f170658", "https://zalo-api.zadn.vn/d/2/a/9/a/12003/preview/440x440.png")],
            "ok": [("0ef7d62cea6903375a78", "https://zalo-api.zadn.vn/9/b/2/3/2/12628/preview/440x440.png")],
            "bye": [("62282cf310b6f9e8a0a7", "https://zalo-api.zadn.vn/8/8/9/b/8/12738/preview/440x440.png")],
            "congrats": [("ef4ef295ced0278e7ec1", "https://zalo-api.zadn.vn/5/a/5/f/a/12689/preview/440x440.png")],
        }


sticker_service = StickerService()
