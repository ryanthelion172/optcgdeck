"""Download English One Piece TCG card data into backend/data/cards.json.

Source: the Punk Records dataset (https://github.com/buhbbl/punk-records),
which is generated from the official Bandai card list.

Run from the backend folder:  python scripts/import_cards.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://raw.githubusercontent.com/buhbbl/punk-records/main/english"
OUT = Path(__file__).resolve().parent.parent / "data" / "cards.json"


def fetch_json(url: str):
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.load(resp)


def to_card(raw: dict, set_label: str | None) -> dict:
    category = raw["category"]
    is_leader = category == "Leader"
    return {
        "id": raw["id"],
        "name": raw["name"],
        "category": category,
        "colors": raw.get("colors") or [],
        # For Leaders the dataset's "cost" field holds the Life value.
        "cost": None if is_leader else raw.get("cost"),
        "life": raw.get("cost") if is_leader else None,
        "power": raw.get("power"),
        "counter": raw.get("counter"),
        "attributes": raw.get("attributes") or [],
        "types": raw.get("types") or [],
        "effect": raw.get("effect") or "",
        "trigger": raw.get("trigger") or "",
        "rarity": raw.get("rarity"),
        # Set code from the card number, e.g. "OP01" from "OP01-016"; promos are "P".
        "set": raw["id"].split("-")[0],
        "pack": set_label,
        "block": raw.get("block_number"),
        "image": raw.get("img_full_url"),
        "variants": [],
    }


def main() -> int:
    packs = fetch_json(f"{BASE}/packs.json")
    index = fetch_json(f"{BASE}/index/cards_by_id.json")
    print(f"{len(index)} entries in index, {len(packs)} packs")

    # Alternate arts are listed as e.g. "OP01-001_p1"; decks use the base id.
    base_ids = [k for k in index if "_" not in k]
    alt_ids = [k for k in index if "_" in k]

    def load(card_id: str):
        entry = index[card_id]
        url = f"{BASE}/cards/{entry['pack_id']}/{card_id}.json"
        try:
            return fetch_json(url)
        except Exception as exc:  # keep going; report at the end
            print(f"  failed {card_id}: {exc}", file=sys.stderr)
            return None

    with ThreadPoolExecutor(max_workers=16) as pool:
        raws = list(pool.map(load, base_ids))

    cards: dict[str, dict] = {}
    for raw in raws:
        if raw is None:
            continue
        pack = packs.get(raw["pack_id"], {})
        label = (pack.get("title_parts") or {}).get("label")
        cards[raw["id"]] = to_card(raw, label)

    for alt in alt_ids:
        base = alt.split("_")[0]
        img = index[alt].get("img_url")
        if base in cards and img:
            cards[base]["variants"].append({"id": alt, "image": img})

    out = sorted(cards.values(), key=lambda c: c["id"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    missing = len(base_ids) - len(cards)
    print(f"wrote {len(out)} cards to {OUT} ({missing} failed)")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
