"""Download English One Piece TCG card data and save it in the `cards` table.

Source: the Punk Records dataset (https://github.com/buhbbl/punk-records),
which is generated from the official Bandai card list.

Fills four tables: `sets` (each pack or deck), `cards` (one per card number),
`card_printings` (the base art and every alternate art, with images) and
`card_names` (each card's Japanese name, from the dataset's Japanese card list,
matched by card number).

New cards are added and changed cards are updated. Cards are never deleted,
so decks that use them keep working even if the source drops a card.

Run from the backend folder, after `python -m alembic upgrade head`:
    python scripts/import_cards.py
Then restart the backend so it picks up the new cards.
"""

from __future__ import annotations

import html
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.cards import upsert_card_names, upsert_cards  # noqa: E402
from app.db import database_url, session_factory  # noqa: E402

ROOT = "https://raw.githubusercontent.com/buhbbl/punk-records/main"
BASE = f"{ROOT}/english"
JAPANESE = f"{ROOT}/japanese/data"


def fetch_json(url: str):
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.load(resp)


def clean(value):
    """The source text keeps HTML escapes like "&amp;"; turn them back into characters."""
    if isinstance(value, str):
        return html.unescape(value)
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def to_set(pack: dict) -> dict:
    parts = pack.get("title_parts") or {}
    return {
        "id": pack["id"],
        "code": parts.get("label") or pack.get("raw_title") or pack["id"],
        "name": clean(parts.get("title")),
        "kind": clean(parts.get("prefix")),
    }


def to_card(raw: dict, set_id: str | None) -> dict:
    raw = {k: clean(v) for k, v in raw.items()}
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
        "set_id": set_id,
        "block": raw.get("block_number"),
        "image": raw.get("img_full_url"),  # the base art (saved in card_printings)
        "variants": [],  # alternate arts (also saved in card_printings)
    }


def fetch_pack(url: str) -> list[dict] | None:
    """A pack's cards, or None if there's no such pack."""
    try:
        return fetch_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def japanese_names(english_packs: dict) -> dict[str, str]:
    """Every Japanese card's name, by card number (the same number as the English card).

    The Japanese data has one file per pack, numbered like the English packs but
    starting "550" (English "569101" is Japanese "550101"). Japan gets sets first,
    so each series is read past the last English pack until a few numbers in a row
    are missing.
    """
    series = "0123456789"  # 550001.., 550101.., ... (some series exist only in Japanese)
    names: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        for s in series:
            number, misses = 1, 0
            while misses < 3:
                batch = [f"550{s}{n:02d}" for n in range(number, number + 8)]
                for pack in pool.map(lambda p: fetch_pack(f"{JAPANESE}/{p}.json"), batch):
                    if pack is None:
                        misses += 1
                        continue
                    misses = 0
                    for card in pack:
                        # Alternate arts ("OP01-016_p1") have the same name as their card.
                        if "_" not in card["id"] and card.get("name"):
                            names[card["id"]] = clean(card["name"])
                number += 8
    return names


def main() -> int:
    load_dotenv(BACKEND / ".env")
    if database_url() is None:
        print("Set DATABASE_URL in backend/.env first.", file=sys.stderr)
        return 2

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

    def set_id(pack_id: str | None) -> str | None:
        return pack_id if pack_id in packs else None

    cards: dict[str, dict] = {}
    for raw in raws:
        if raw is None:
            continue
        cards[raw["id"]] = to_card(raw, set_id(raw.get("pack_id")))

    alts = 0
    for alt in alt_ids:
        base = alt.split("_")[0]
        img = index[alt].get("img_url")
        if base in cards and img:
            cards[base]["variants"].append({"id": alt, "image": img, "set_id": set_id(index[alt].get("pack_id"))})
            alts += 1

    sets = [to_set({**pack, "id": pack_id}) for pack_id, pack in packs.items()]
    with session_factory()() as db:
        saved = upsert_cards(db, list(cards.values()), sets)
    missing = len(base_ids) - len(cards)
    print(f"saved {len(sets)} sets, {saved} cards and {alts} alternate arts ({missing} cards failed to download)")

    try:
        ja = japanese_names(packs)
    except Exception as exc:  # the English cards are saved; don't fail the import over names
        print(f"Couldn't download Japanese names: {exc}", file=sys.stderr)
    else:
        with session_factory()() as db:
            named = upsert_card_names(db, ja, "ja")
        print(f"saved Japanese names for {named} cards ({len(ja) - named} Japanese-only cards skipped)")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
