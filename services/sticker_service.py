import logging
import os
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

    The sticker catalog is persisted to data/sticker_catalog.json so it does
    not depend on the Zalo Sticker Store API at runtime.  On first startup (or
    when /sticker refresh is called), the catalog is fetched from
    https://stickers.zaloapp.com/sticker, mapped to sentiment tags, and saved
    to disk.  sendSticker receives the pack id registered on the store; if Zalo
    rejects it, we fall back to sendPhoto with the pack preview image.
    """

    def __init__(self):
        self._catalog: Optional[Dict[str, List[Tuple[str, str]]]] = None
        self._last_fetch_error: Optional[str] = None
        self._catalog_path = os.path.join(os.path.dirname(settings.DB_PATH), "sticker_catalog.json")
        os.makedirs(os.path.dirname(self._catalog_path), exist_ok=True)

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
            lines.append(f"\n⚠️ Lưu ý: lỗi fetch gần nhất ({self._last_fetch_error}).")
        lines.append("\nGõ /sticker <tên> để bot gửi thử. Ví dụ: /sticker laugh")
        return "\n".join(lines)

    def refresh_catalog(self) -> Tuple[bool, str]:
        """Force re-fetch from Zalo Sticker Store and save to disk."""
        catalog = self._fetch_zalo_sticker_catalog(force=True)
        if catalog is None:
            return False, f"❌ Không thể cập nhật kho sticker: {self._last_fetch_error or 'unknown error'}"
        self._catalog = catalog
        self._save_catalog(catalog)
        total = sum(len(v) for v in catalog.values())
        return True, f"✅ Đã cập nhật kho sticker: {total} bộ sticker trong {len(catalog)} nhóm."

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_catalog(self) -> Dict[str, List[Tuple[str, str]]]:
        """Lazy-load sticker catalog from disk, env override, or Zalo store."""
        if self._catalog is not None:
            return self._catalog

        # 1. Env override wins.
        if settings.STICKER_CATALOG_JSON:
            try:
                self._catalog = self._parse_catalog_json(settings.STICKER_CATALOG_JSON)
                logger.info("Loaded custom sticker catalog from STICKER_CATALOG_JSON")
                return self._catalog
            except Exception as e:
                logger.warning(f"Invalid STICKER_CATALOG_JSON, falling back: {e}")

        # 2. Load from local JSON file if exists.
        local = self._load_catalog()
        if local is not None:
            self._catalog = local
            logger.info(f"Loaded sticker catalog from {self._catalog_path}")
            return self._catalog

        # 3. Fetch from Zalo sticker store and persist.
        live_catalog = self._fetch_zalo_sticker_catalog(force=False)
        if live_catalog:
            self._catalog = live_catalog
            self._save_catalog(live_catalog)
            return self._catalog

        # 4. Fallback to built-in set.
        self._catalog = self._default_catalog()
        return self._catalog

    def _load_catalog(self) -> Optional[Dict[str, List[Tuple[str, str]]]]:
        """Read catalog from local JSON file."""
        if not os.path.exists(self._catalog_path):
            return None
        try:
            with open(self._catalog_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return self._parse_catalog_dict(raw)
        except Exception as e:
            logger.warning(f"Failed to load local sticker catalog: {e}")
            return None

    def _save_catalog(self, catalog: Dict[str, List[Tuple[str, str]]]) -> None:
        """Persist catalog to local JSON file (serializable format)."""
        try:
            serializable: Dict[str, List[Dict[str, str]]] = {}
            for tag, items in catalog.items():
                serializable[tag] = [{"id": item[0], "preview_url": item[1]} for item in items]
            with open(self._catalog_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved sticker catalog to {self._catalog_path}")
        except Exception as e:
            logger.warning(f"Failed to save sticker catalog: {e}")

    def _parse_catalog_json(self, json_str: str) -> Dict[str, List[Tuple[str, str]]]:
        raw = json.loads(json_str)
        return self._parse_catalog_dict(raw)

    @staticmethod
    def _parse_catalog_dict(raw: Dict) -> Dict[str, List[Tuple[str, str]]]:
        """Normalize a catalog dict to Dict[tag, List[(id, preview_url)]]."""
        catalog: Dict[str, List[Tuple[str, str]]] = {}
        for tag, entries in raw.items():
            catalog[tag] = []
            for entry in entries:
                if isinstance(entry, dict):
                    catalog[tag].append((entry.get("id", ""), entry.get("preview_url", entry.get("url", ""))))
                elif isinstance(entry, str):
                    catalog[tag].append((entry, entry))
        return catalog

    def _fetch_zalo_sticker_catalog(self, force: bool = False) -> Optional[Dict[str, List[Tuple[str, str]]]]:
        """Fetch sticker packs from https://stickers.zaloapp.com/sticker and map to sentiments."""
        try:
            r = requests.get(
                "https://stickers.zaloapp.com/sticker",
                timeout=(10, 20),
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

            logger.info(f"Fetched {sum(len(v) for v in catalog.values())} sticker packs from Zalo store")
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
