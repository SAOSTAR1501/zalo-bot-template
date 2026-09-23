#!/usr/bin/env python3
"""
Generate data/sticker_catalog.json by fetching all public sticker packs and their
individual stickers from https://stickers.zaloapp.com.

For every pack found on the store page, the script:
  1. Classifies the pack into one or more sentiment tags based on its name.
  2. Calls /cate-stickers?cid=<pack_id> to fetch every child sticker id.
  3. Writes the full sticker catalog to data/sticker_catalog.json.

Run locally or on the server:
    python scripts/generate_sticker_catalog.py

Note: Zalo Bot Platform may reject some sticker ids with error 425 if the
sticker pack is not registered for the bot.  Use this catalog as a starting set
and remove rejected ids if necessary.
"""

import json
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Set, Tuple

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings


STICKER_STORE_URL = "https://stickers.zaloapp.com/sticker"
STICKER_CHILDREN_URL = "https://stickers.zaloapp.com/cate-stickers"

# Regex patterns per sentiment tag. Patterns are matched against the lowercased
# Vietnamese pack name.
CLASSIFICATION: List[Tuple[str, List[str]]] = [
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


def classify_pack(name: str) -> Set[str]:
    name_norm = name.lower().strip()
    if name_norm in OVERRIDES:
        return {OVERRIDES[name_norm]}
    tags: Set[str] = set()
    for tag, patterns in CLASSIFICATION:
        if any(re.search(p, name_norm) for p in patterns):
            tags.add(tag)
    return tags


def fetch_pack_stickers(session, pack: Dict[str, str]) -> Tuple[str, str, Set[str], List[Dict[str, str]]]:
    """Return (pack_id, pack_name, tags, child_stickers)."""
    import requests

    pack_id = pack.get("id", "")
    name = pack.get("name", "")
    tags = classify_pack(name)
    if not tags:
        tags = {"ok"}

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
    except requests.RequestException as e:
        print(f"   ⚠️  failed to fetch children for {name} ({pack_id}): {e}")
        children = []

    return pack_id, name, tags, children


def build_catalog(packs: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    import requests

    catalog: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    seen: Set[str] = set()

    session = requests.Session()
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(fetch_pack_stickers, session, pack) for pack in packs]
        for i, future in enumerate(as_completed(futures), start=1):
            pack_id, name, tags, children = future.result()
            print(f"   [{i}/{len(packs)}] {name}: {len(children)} stickers -> {tags}")
            for child in children:
                child_id = child.get("id", "")
                child_url = child.get("url", "")
                if not child_id or child_id in seen:
                    continue
                seen.add(child_id)
                for tag in tags:
                    catalog[tag].append({"id": child_id, "preview_url": child_url})

    return dict(catalog)


def main() -> None:
    print("📦 Fetching sticker packs from Zalo Sticker Store...")
    packs = fetch_packs()
    print(f"   Found {len(packs)} packs")

    print("🏷️  Classifying packs and fetching individual sticker ids...")
    catalog = build_catalog(packs)

    total = sum(len(items) for items in catalog.values())
    print(f"\n   Total unique stickers collected: {total}")
    for tag, items in sorted(catalog.items()):
        print(f"   • {tag}: {len(items)} stickers")

    output_dir = os.path.dirname(settings.DB_PATH)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "sticker_catalog.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Saved sticker catalog to {output_path}")


if __name__ == "__main__":
    main()
