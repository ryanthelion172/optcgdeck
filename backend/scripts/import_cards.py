"""Download English One Piece TCG card data and save it in the `cards` table.

Source: the Punk Records dataset (https://github.com/buhbbl/punk-records),
which is generated from the official Bandai card list.

Fills four tables: `sets` (each pack or deck), `cards` (one per card number),
`card_printings` (the base art and every alternate art, with images) and
`card_names` (each card's Japanese name).

The English (North America/Europe) list is the main one. The dataset's other
lists (English Asia, Japanese, Chinese, Thai, French) are also read, for
alternate arts the English list doesn't have and for Japanese names. Card
numbers are the same in every language, so they're matched by number.

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


# Other card lists in the dataset, checked for printings the English list doesn't
# have (alternate arts sold or listed only in one region), in this order. The
# third value is the pack number prefix, used when a list has no index file.
OTHER_LANGUAGES = [
    ("english-asia", "en-asia", None),
    ("japanese", "ja", "550"),
    ("chinese-hongkong", "zh-hk", None),
    ("chinese-taiwan", "zh-tw", None),
    ("thai", "th", None),
    ("french", "fr", None),
]


def language_cards(folder: str, prefix: str | None) -> list[dict]:
    """Every card and printing in one language's list, as {"id", "name", "image"}.

    Uses the list's index file. The Japanese index is empty, so its packs are read
    instead: one file per pack, numbered like the English ones but starting "550"
    (English "569101" is Japanese "550101"). Each series is read until a few
    numbers in a row are missing, since Japan gets sets first.
    """
    index = fetch_json(f"{ROOT}/{folder}/index/cards_by_id.json")
    if index:
        return [{"id": k, "name": clean(v.get("name")), "image": v.get("img_url")} for k, v in index.items()]
    if not prefix:
        return []
    found: list[dict] = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for series in "0123456789":
            number, misses = 1, 0
            while misses < 3:
                batch = [f"{prefix}{series}{n:02d}" for n in range(number, number + 8)]
                for pack in pool.map(lambda p: fetch_pack(f"{ROOT}/{folder}/data/{p}.json"), batch):
                    if pack is None:
                        misses += 1
                        continue
                    misses = 0
                    found += [{"id": c["id"], "name": clean(c.get("name")), "image": c.get("img_full_url")} for c in pack]
                number += 8
    return found


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

    # Printings that only other regions' lists have (e.g. "Limited Product Card"
    # alternate arts listed only on the Asia site). Card numbers are the same in
    # every language, so they're added to our card with that number. Each
    # language's names are kept too (Japanese for now).
    have = set(index)
    extra: dict[str, int] = {}
    other_names: dict[str, dict[str, str]] = {}
    for folder, code, prefix in OTHER_LANGUAGES:
        try:
            listed = language_cards(folder, prefix)
        except Exception as exc:  # one list failing shouldn't stop the import
            print(f"  couldn't read the {folder} card list: {exc}", file=sys.stderr)
            continue
        other_names[code] = {c["id"]: c["name"] for c in listed if "_" not in c["id"] and c["name"]}
        for c in listed:
            base = c["id"].split("_")[0]
            if "_" in c["id"] and c["id"] not in have and base in cards and c["image"]:
                cards[base]["variants"].append({"id": c["id"], "image": c["image"], "set_id": None, "language": code})
                have.add(c["id"])
                extra[code] = extra.get(code, 0) + 1

    sets = [to_set({**pack, "id": pack_id}) for pack_id, pack in packs.items()]
    with session_factory()() as db:
        saved = upsert_cards(db, list(cards.values()), sets)
    missing = len(base_ids) - len(cards)
    print(f"saved {len(sets)} sets, {saved} cards and {alts} alternate arts ({missing} cards failed to download)")

    if extra:
        print("  alternate arts only in other lists: " + ", ".join(f"{n} {code}" for code, n in extra.items()))
    if ja := other_names.get("ja"):
        with session_factory()() as db:
            named = upsert_card_names(db, ja, "ja")
        print(f"saved Japanese names for {named} cards ({len(ja) - named} Japanese-only cards skipped)")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
