#!/usr/bin/env python3
"""
Generate data/sticker_catalog.json by fetching all public sticker packs and their
individual stickers from https://stickers.zaloapp.com.

Output structure (flat pack-name catalog):
{
  "Bư Mặt Ngáo": [{"id": "...", "preview_url": "..."}, ...],
  "Zapy Công Sở": [...],
  ...
}

This lets users send stickers by pack name via /sticker <tên bộ>.
Each pack can contain many different emotions, so we keep them grouped by pack
name instead of trying to tag every individual sticker.

Run locally or on the server:
    python scripts/generate_sticker_catalog.py
"""

import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Settings import is optional; this script is meant to be runnable on its own.
try:
    from config.settings import settings
    _db_path = settings.DB_PATH
except Exception:  # pragma: no cover - allow running without project deps
    _db_path = "data/zalo_bot.db"


STICKER_STORE_URL = "https://stickers.zaloapp.com/sticker"
STICKER_CHILDREN_URL = "https://stickers.zaloapp.com/cate-stickers"


def fetch_packs() -> List[Dict[str, str]]:
    import requests

    r = requests.get(
        STICKER_STORE_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://stickers.zaloapp.com/",
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    packs = data.get("value", {}).get("all", [])
    if not packs:
        raise ValueError("No sticker packs returned from store")
    return packs


def fetch_pack_stickers(session, pack: Dict[str, str]) -> Tuple[str, List[Dict[str, str]]]:
    """Return (pack_name, child_stickers)."""
    import requests

    pack_id = pack.get("id", "")
    name = pack.get("name", "")
    try:
        r = session.get(
            STICKER_CHILDREN_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": f"https://stickers.zaloapp.com/oa/detail?cid={pack_id}",
            },
            params={"cid": pack_id},
            timeout=15,
        )
        if r.status_code == 200:
            try:
                children = r.json().get("value", [])
            except Exception:
                children = []
        else:
            children = []
    except Exception:
        children = []

    return name, children


def build_catalog(packs: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    import requests

    catalog: Dict[str, List[Dict[str, str]]] = {}
    seen_pack_names: set = set()

    session = requests.Session()
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(fetch_pack_stickers, session, pack) for pack in packs]
        for i, future in enumerate(as_completed(futures), start=1):
            name, children = future.result()
            print(f"   [{i}/{len(packs)}] {name}: {len(children)} stickers")

            if not children:
                continue

            # Preserve unique pack names (append a small index if duplicated)
            display_name = name.strip()
            suffix = 2
            while display_name in seen_pack_names:
                display_name = f"{name.strip()} ({suffix})"
                suffix += 1
            seen_pack_names.add(display_name)

            catalog[display_name] = [
                {"id": child.get("id", ""), "preview_url": child.get("url", "")}
                for child in children
                if child.get("id")
            ]

    return catalog


def main() -> None:
    print("📦 Fetching sticker packs from Zalo Sticker Store...")
    packs = fetch_packs()
    print(f"   Found {len(packs)} packs")

    print("🏷️  Fetching individual sticker ids per pack...")
    catalog = build_catalog(packs)

    total_stickers = sum(len(items) for items in catalog.values())
    print(f"\n   Total packs with stickers: {len(catalog)}")
    print(f"   Total unique stickers: {total_stickers}")

    output_dir = os.path.dirname(_db_path)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "sticker_catalog.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Saved sticker catalog to {output_path}")


if __name__ == "__main__":
    main()
