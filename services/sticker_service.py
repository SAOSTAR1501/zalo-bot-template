import logging
import os
import random
import re
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

    IMPORTANT: Zalo Bot Platform's sendSticker API only accepts sticker
    references (pack ids) that have been explicitly registered/allowed.
    There is NO public API to automatically discover these ids from the
    sticker store.  Therefore this service ONLY uses a user-managed catalog:

      - data/sticker_catalog.json   (local file, committed or edited on server)
      - STICKER_CATALOG_JSON env var (override)

    Each catalog entry must contain:
      - "id": the sticker pack id, e.g. "613dece5d0a039fe60b1"
      - "preview_url": optional fallback image URL for sendPhoto

    Admins can find pack ids from https://stickers.zaloapp.com/oa/detail?cid=...
    and add them to the catalog.
    """

    def __init__(self):
        self._catalog: Optional[Dict[str, List[Tuple[str, str]]]] = None
        self._catalog_path = os.path.join(os.path.dirname(settings.DB_PATH), "sticker_catalog.json")
        os.makedirs(os.path.dirname(self._catalog_path), exist_ok=True)
        self._seed_default_catalog_if_empty()

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
            ids = ", ".join(item[0] for item in items)
            lines.append(f"• {tag}: {len(items)} bộ (id: {ids})")
        lines.append(
            "\n👉 Để thêm sticker, lấy id từ https://stickers.zaloapp.com/oa/detail?cid=<ID> "
            "rồi thêm vào data/sticker_catalog.json hoặc STICKER_CATALOG_JSON."
        )
        lines.append("👉 Ví dụ: /sticker laugh")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_catalog(self) -> Dict[str, List[Tuple[str, str]]]:
        """Load sticker catalog from env override or local JSON file."""
        if self._catalog is not None:
            return self._catalog

        # 1. Env override wins.
        if settings.STICKER_CATALOG_JSON:
            try:
                self._catalog = self._parse_catalog_json(settings.STICKER_CATALOG_JSON)
                logger.info("Loaded sticker catalog from STICKER_CATALOG_JSON")
                return self._catalog
            except Exception as e:
                logger.warning(f"Invalid STICKER_CATALOG_JSON, falling back: {e}")

        # 2. Load from local JSON file if exists.
        local = self._load_catalog()
        if local is not None:
            self._catalog = local
            logger.info(f"Loaded sticker catalog from {self._catalog_path}")
            return self._catalog

        # 3. Seed default catalog.
        self._catalog = self._default_catalog()
        self._save_catalog(self._catalog)
        logger.info(f"Seeded default sticker catalog to {self._catalog_path}")
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
                    sticker_id = entry.get("id", "")
                    preview_url = entry.get("preview_url", entry.get("url", ""))
                    if sticker_id:
                        catalog[tag].append((sticker_id, preview_url))
                elif isinstance(entry, str):
                    catalog[tag].append((entry, ""))
        return catalog

    def _seed_default_catalog_if_empty(self) -> None:
        """If no catalog file exists, create one with example sticker pack ids."""
        if os.path.exists(self._catalog_path) or settings.STICKER_CATALOG_JSON:
            return
        default = self._default_catalog()
        self._save_catalog(default)

    def _default_catalog(self) -> Dict[str, List[Tuple[str, str]]]:
        """
        Default starter catalog with a few example sticker pack ids.
        Replace these ids with ones registered for your bot.
        """
        return {
            "hello": [("34c1ca1af65f1f01464e", "")],
            "laugh": [("34c1ca1af65f1f01464e", "")],
            "love": [("bf596d9a51dfb881e1ce", "")],
            "cry": [("e5c88a0cb6495f170658", "")],
            "ok": [("0ef7d62cea6903375a78", "")],
            "bye": [("62282cf310b6f9e8a0a7", "")],
            "congrats": [("ef4ef295ced0278e7ec1", "")],
        }


sticker_service = StickerService()
