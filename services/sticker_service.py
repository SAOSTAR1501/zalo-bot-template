import logging
import os
import random
import json
from typing import Optional, List, Dict, Tuple
from config.settings import settings

logger = logging.getLogger(__name__)


class StickerService:
    """
    Sticker picker for Zalo Bot.

    Catalog format (data/sticker_catalog.json):
    {
      "Bư Mặt Ngáo": [{"id": "...", "preview_url": "..."}, ...],
      "Zapy Công Sở": [...],
      ...
    }

    Users send stickers by pack name:
      /sticker Bư Mặt Ngáo
      /sticker "Mimi & Neko 6"

    Each pack contains many different expressions, so we keep them grouped by
    pack name and pick a random sticker from the requested pack.
    """

    def __init__(self):
        self._catalog: Optional[Dict[str, List[Dict[str, str]]]] = None
        self._catalog_path = os.path.join(os.path.dirname(settings.DB_PATH), "sticker_catalog.json")
        os.makedirs(os.path.dirname(self._catalog_path), exist_ok=True)
        self._seed_default_catalog_if_empty()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def available_pack_names(self) -> List[str]:
        return sorted(self._get_catalog().keys())

    def get_sticker(self, pack_name: str) -> Optional[Tuple[str, str]]:
        """
        Return a random (sticker_id, preview_url) from the named pack,
        or None if unknown.
        """
        pack_name = pack_name.strip()
        catalog = self._get_catalog()

        # Exact match first
        if pack_name in catalog:
            items = catalog[pack_name]
        else:
            # Case-insensitive fallback
            lookup = {k.lower(): k for k in catalog.keys()}
            real_name = lookup.get(pack_name.lower())
            if not real_name:
                return None
            items = catalog[real_name]

        if not items:
            return None
        chosen = random.choice(items)
        return chosen["id"], chosen.get("preview_url", "")

    def list_catalog(self, full: bool = False) -> str:
        catalog = self._get_catalog()
        total = sum(len(v) for v in catalog.values())
        pack_names = sorted(catalog.keys())

        lines = [
            "🎨 KHO STICKER CỦA BOT:",
            f"• Tổng số bộ sticker: {len(catalog)}",
            f"• Tổng số sticker: {total}",
            "",
            "👉 Gửi theo tên bộ: /sticker <tên bộ>",
            '   Ví dụ: /sticker Bư Mặt Ngáo',
            '          /sticker "Mimi & Neko 6"',
            "",
            "📦 Danh sách bộ sticker:",
        ]

        if full:
            for pack_name in pack_names:
                lines.append(f"• {pack_name}: {len(catalog[pack_name])} sticker")
        else:
            preview_count = min(30, len(pack_names))
            for pack_name in pack_names[:preview_count]:
                lines.append(f"• {pack_name}: {len(catalog[pack_name])} sticker")
            remaining = len(pack_names) - preview_count
            if remaining > 0:
                lines.append(f"\n...và thêm {remaining} bộ khác.")
                lines.append("Gõ /sticker list để xem toàn bộ.")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_catalog(self) -> Dict[str, List[Dict[str, str]]]:
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

    def _load_catalog(self) -> Optional[Dict[str, List[Dict[str, str]]]]:
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

    def _save_catalog(self, catalog: Dict[str, List[Dict[str, str]]]) -> None:
        """Persist catalog to local JSON file."""
        try:
            with open(self._catalog_path, "w", encoding="utf-8") as f:
                json.dump(catalog, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved sticker catalog to {self._catalog_path}")
        except Exception as e:
            logger.warning(f"Failed to save sticker catalog: {e}")

    def _parse_catalog_json(self, json_str: str) -> Dict[str, List[Dict[str, str]]]:
        raw = json.loads(json_str)
        return self._parse_catalog_dict(raw)

    @staticmethod
    def _parse_catalog_dict(raw: Dict) -> Dict[str, List[Dict[str, str]]]:
        """Normalize a catalog dict to Dict[pack_name, List[{id, preview_url}]]."""
        # New flat format: {pack_name: [{id, preview_url}]}
        if all(isinstance(v, list) for v in raw.values()):
            catalog: Dict[str, List[Dict[str, str]]] = {}
            for pack_name, entries in raw.items():
                catalog[pack_name] = []
                for entry in entries:
                    if isinstance(entry, dict):
                        sticker_id = entry.get("id", "")
                        preview_url = entry.get("preview_url", entry.get("url", ""))
                        if sticker_id:
                            catalog[pack_name].append({"id": sticker_id, "preview_url": preview_url})
                    elif isinstance(entry, str) and entry:
                        catalog[pack_name].append({"id": entry, "preview_url": ""})
            return catalog

        # Legacy {packs, sentiments} format
        if "packs" in raw:
            return StickerService._migrate_nested_catalog(raw)

        # Legacy flat tag format: {tag: [{id, preview_url}]}
        catalog = {}
        for tag, entries in raw.items():
            catalog[tag] = []
            for entry in entries:
                if isinstance(entry, dict):
                    sticker_id = entry.get("id", "")
                    preview_url = entry.get("preview_url", entry.get("url", ""))
                    if sticker_id:
                        catalog[tag].append({"id": sticker_id, "preview_url": preview_url})
                elif isinstance(entry, str) and entry:
                    catalog[tag].append({"id": entry, "preview_url": ""})
        logger.warning("Legacy flat sticker catalog detected; using tag names as pack names.")
        return catalog

    @staticmethod
    def _migrate_nested_catalog(raw: Dict) -> Dict[str, List[Dict[str, str]]]:
        """Convert legacy {packs, sentiments} catalog to flat pack-based format."""
        logger.warning("Legacy nested sticker catalog detected; migrating to flat pack format.")
        return raw.get("packs", {})

    def _seed_default_catalog_if_empty(self) -> None:
        """If no catalog file exists, create one with example sticker ids."""
        if os.path.exists(self._catalog_path) or settings.STICKER_CATALOG_JSON:
            return
        default = self._default_catalog()
        self._save_catalog(default)

    def _default_catalog(self) -> Dict[str, List[Dict[str, str]]]:
        """Default starter catalog with a few example sticker ids."""
        return {
            "Bư Mặt Ngáo": [
                {"id": "e485deaae2ef0bb152fe", "preview_url": ""},
            ],
        }


sticker_service = StickerService()
