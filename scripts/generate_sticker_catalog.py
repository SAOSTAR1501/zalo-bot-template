#!/usr/bin/env python3
"""
Generate data/sticker_catalog.json by fetching all public sticker packs from
https://stickers.zaloapp.com and mapping pack names to sentiment tags.

Run locally or on the server:
    python scripts/generate_sticker_catalog.py

The output is written to data/sticker_catalog.json and loaded by the bot at
startup.  Only registered sticker pack ids work with Zalo Bot Platform's
sendSticker API; this script helps collect candidate ids from the public store.
"""

import json
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings


STICKER_STORE_URL = "https://stickers.zaloapp.com/sticker"

# Regex patterns per sentiment tag. Patterns are matched against the lowercased
# Vietnamese pack name.
CLASSIFICATION = [
    ("hello", [r"\bchào\b", r"\bsay hi\b", r"\bwaving\b", r"\bxin chào\b",
               r"\bhello\b", r"\bhi\b", r"\bbuổi sáng\b", r"\bbuổi tối\b",
               r"\bgood morning\b", r"\bsáng\b"]),
    ("bye", [r"\btạm biệt\b", r"\bbye\b", r"\bsee you\b", r"\bđi ngủ\b",
              r"\bngủ ngon\b", r"\bgood night\b"]),
    ("thanks", [r"\bcảm ơn\b", r"\bthank\b", r"\bcám ơn\b", r"\bbiết ơn\b"]),
    ("sorry", [r"\bxin lỗi\b", r"\bsorry\b", r"\băn năn\b", r"\bhối lỗi\b"]),
    ("laugh", [r"\bcười\b", r"\bhaha\b", r"\bhihi\b", r"\bhehe\b", r"\bvui\b",
                r"\bhài\b", r"\bcười xỉu\b", r"\bfunny\b", r"\blaugh\b",
                r"\bhí hửng\b", r"\bngáo\b", r"\bdô tri\b", r"\bnhí nhố\b", r"\blú lẫn\b"]),
    ("love", [r"\byêu\b", r"\blove\b", r"\bthương\b", r"\bkiss\b", r"\bcouple\b",
               r"\btình yêu\b", r"\bđang yêu\b", r"\bngọt ngào\b", r"\bromantic\b"]),
    ("cry", [r"\bkhóc\b", r"\bbuồn\b", r"\bcry\b", r"\bsad\b", r"\bmếu\b",
              r"\btủi thân\b", r"\bnước mắt\b", r"\bkhổ\b"]),
    ("angry", [r"\bgiận\b", r"\btức\b", r"\bangry\b", r"\bbực\b", r"\bcáu\b",
                r"\bnóng\b", r"\btức giận\b", r"\bnóng giận\b"]),
    ("motivation", [r"\bcố lên\b", r"\bđừng bỏ cuộc\b", r"\bfighting\b",
                     r"\bcố gắng\b", r"\bquyết tâm\b"]),
    ("congrats", [r"\bchúc mừng\b", r"\bcongrats\b", r"\bmừng\b", r"\bgiỏi\b",
                   r"\btuyệt\b", r"\bxuất sắc\b", r"\bhooray\b", r"\byeah\b",
                   r"\bcongratulation\b", r"\băn mừng\b"]),
    ("ok", [r"\bok\b", r"\boke\b", r"\bđồng ý\b", r"\bđược\b", r"\byes\b",
             r"\bokay\b", r"\bchấp nhận\b"]),
]

# Hard overrides for well-known packs whose names do not obviously match a tag.
OVERRIDES: Dict[str, str] = {
    "bư mặt ngáo": "laugh",
    "zapy công sở": "hello",
    "zapy dô tri": "laugh",
    "zapy giáng sinh": "congrats",
    "bư đón tết": "congrats",
    "thiếu nhi việt nam": "hello",
    "bé dúi": "cry",
    "snubby story 1": "laugh",
    "snubby story 2": "laugh",
    "mimi & neko 5": "love",
    "mimi & neko 6": "love",
    "mimi & neko couple": "love",
    "lovely sugar cubs": "love",
    "sweet sugar cubs": "love",
    "yêu quá đi": "love",
    "zookiz đang yêu": "love",
    "zookiz zô tri": "laugh",
    "thỏ cáu kỉnh": "angry",
    "thỏ cáu kỉnh 2": "angry",
    "kim & yim nóng nảy": "angry",
    "cò lõ đi làm ổnt mà": "cry",
    "moonie múp míp": "cry",
    "hổ béo hằng ngày 01": "laugh",
    "tom nhí nhố": "laugh",
    "cà méo ngáo ngơ": "laugh",
    "hội rau củ lú lẫn": "laugh",
    "usagyuuun ngốc nghếch": "laugh",
    "usagyuuun hay ra dẻ": "laugh",
    "usagyuuun tăng động 2": "laugh",
    "bình hưng hòa xanh": "hello",
    "anh tre say hi": "hello",
    "binie nè": "hello",
    "gấu bông xanh": "hello",
    "quỳnh aka và em": "love",
    "quỳnh aka bất bại": "laugh",
    "quỳnh aka nghỉ lễ": "bye",
    "vũ trụ bmz": "hello",
    "bida zagoo": "ok",
    "cá văn phòng 1": "hello",
    "cá văn phòng 2": "hello",
    "cậu vàng lilyellow": "hello",
    "chim xanh giả trân": "laugh",
    "cô dứa": "hello",
    "cột sống zookiz": "angry",
    "crazy frog 2": "laugh",
    "draco": "hello",
    "fantastic sumo 1": "laugh",
    "fantastic sumo 2": "laugh",
    "fluffy puppy": "hello",
    "gấu đụt & cánh cụt": "hello",
    "happy kkotka": "hello",
    "hư ngoan có đủ": "laugh",
    "i am binie": "hello",
    "lazycactus": "hello",
    "life at vng": "hello",
    "meme boss cat": "laugh",
    "mèo méo meo": "laugh",
    "mobile girl, mim": "hello",
    "nhật kí của mẹ": "love",
    "noo-hin": "laugh",
    "phật giáo": "motivation",
    "ppuyo póng pẩy": "hello",
    "putapi & pet": "hello",
    "rồng lý sự": "angry",
    "scottie friends": "hello",
    "sickyaki": "hello",
    "sugar cubs": "love",
    "sugar cubs 2": "love",
    "truyện cổ remix": "laugh",
    "trọc trắng": "hello",
    "zameo rốn lồi": "laugh",
    "zcá mập zagoo": "hello",
    "zookiz cục súc": "angry",
    "zookiz mầm non": "hello",
    "zookiz pang xù": "hello",
    "zookiz quẩy xuyên hè": "hello",
    "zookiz sở thú xàm xí": "laugh",
    "zookiz vô tri": "laugh",
    "zookiz xuân xập xình": "congrats",
    "zookiz đang yêu": "love",
    "zookiz du xuân": "congrats",
}


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


def classify_pack(name: str) -> set:
    name_norm = name.lower().strip()
    if name_norm in OVERRIDES:
        return {OVERRIDES[name_norm]}
    tags = set()
    for tag, patterns in CLASSIFICATION:
        if any(re.search(p, name_norm) for p in patterns):
            tags.add(tag)
    return tags


def build_catalog(packs: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    catalog: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    seen = set()
    for pack in packs:
        pack_id = pack.get("id", "")
        name = pack.get("name", "")
        preview = pack.get("thumbImg") or pack.get("iconUrl") or ""
        if not pack_id or pack_id in seen:
            continue
        seen.add(pack_id)
        tags = classify_pack(name)
        for tag in tags:
            catalog[tag].append({"id": pack_id, "preview_url": preview})

    # Packs with no tag go to "ok" as a safe default
    for pack in packs:
        pack_id = pack.get("id", "")
        if pack_id not in seen:
            continue
        found = any(
            any(item["id"] == pack_id for item in items)
            for items in catalog.values()
        )
        if not found:
            catalog["ok"].append({
                "id": pack_id,
                "preview_url": pack.get("thumbImg") or pack.get("iconUrl") or "",
            })

    return dict(catalog)


def main():
    print("📦 Fetching sticker packs from Zalo Sticker Store...")
    packs = fetch_packs()
    print(f"   Found {len(packs)} packs")

    print("🏷️  Classifying packs by name...")
    catalog = build_catalog(packs)

    for tag, items in sorted(catalog.items()):
        print(f"   • {tag}: {len(items)} packs")

    output_dir = os.path.dirname(settings.DB_PATH)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "sticker_catalog.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Saved sticker catalog to {output_path}")


if __name__ == "__main__":
    main()
