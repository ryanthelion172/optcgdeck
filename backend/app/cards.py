"""The card list, read from the `cards` table and kept in memory.

Cards change only when scripts/import_cards.py runs, so the server reads the
table once and serves it from memory. Restart the backend after an import to
pick up new cards.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .db import database_url, session_factory
from .models import Card, CardName, CardPrinting, Set


class CardStore:
    def __init__(self, cards: list[dict], printings: list[dict] | None = None) -> None:
        # Base arts only: alternate arts stay on the backend (see load_printings).
        cards = [{k: v for k, v in c.items() if k != "variants"} for c in cards]
        self.cards = sorted(cards, key=lambda c: c["id"])
        self.by_id: dict[str, dict] = {c["id"]: c for c in self.cards}
        # Alternate arts by id, as {"id", "image"}, so their images can be served
        # (photo scanning shows the alternate art it matched).
        self.alt_arts: dict[str, dict] = {
            p["id"].upper(): {"id": p["id"], "image": p["image"]} for p in printings or [] if not p["is_base"]
        }
        self.json = json.dumps(self.cards, ensure_ascii=False, separators=(",", ":")).encode()
        # Changes whenever the card data changes, so browsers can cache it.
        self.etag = '"' + hashlib.sha256(self.json).hexdigest()[:16] + '"'

    def get(self, card_id: str) -> dict | None:
        return self.by_id.get(card_id.upper())

    def alt_art(self, printing_id: str) -> dict | None:
        """An alternate art, e.g. "OP01-016_p1", as {"id", "image"}."""
        return self.alt_arts.get(printing_id.upper())


def load_cards(db: Session) -> list[dict]:
    return [card.to_dict() for card in db.scalars(select(Card).order_by(Card.id))]


def load_printings(db: Session) -> list[dict]:
    """Every printing (base and alternate arts) with its image, for photo scanning."""
    rows = db.scalars(select(CardPrinting).order_by(CardPrinting.id))
    return [
        {"id": p.id, "card_id": p.card_id, "is_base": p.is_base, "image": p.image_url, "language": p.language}
        for p in rows
    ]


@lru_cache(maxsize=1)
def _load_store() -> CardStore:
    with session_factory()() as db:
        return CardStore(load_cards(db), load_printings(db))


def get_store() -> CardStore:
    """FastAPI dependency: the card list, loaded from the database the first time."""
    if database_url() is None:
        raise HTTPException(status_code=503, detail="Set DATABASE_URL in backend/.env to load cards.")
    return _load_store()


def reload_store() -> None:
    _load_store.cache_clear()


def _upsert(db: Session, model, rows: list[dict]) -> None:
    """Inserts rows, updating any that already exist (matched on the primary key)."""
    for start in range(0, len(rows), 500):
        chunk = rows[start : start + 500]
        stmt = insert(model).values(chunk)
        updatable = {col: stmt.excluded[col] for col in chunk[0] if col != "id"}
        updatable["updated_at"] = func.now()
        db.execute(stmt.on_conflict_do_update(index_elements=[model.id], set_=updatable))


def upsert_cards(db: Session, cards: list[dict], sets: list[dict] | None = None) -> int:
    """Adds new sets, cards and printings, and updates existing ones. Never deletes anything.

    Takes cards in the shape the import script builds: the frontend shape (with
    "set"), plus "set_id", the base art's "image", and "variants", the
    alternate arts as [{"id": "OP01-001_p1", "image": "...", "set_id": "...", "language": "en"}]
    ("language": which region's card list it came from, "en" if left out).
    `sets` are {"id", "code", "name", "kind"}.
    """
    if sets:
        _upsert(db, Set, [{"id": s["id"], "code": s["code"], "name": s.get("name"), "kind": s.get("kind")} for s in sets])
    card_fields = {c.key for c in Card.__table__.columns} - {"updated_at"}
    rows, printings = [], []
    for c in cards:
        row = {k: v for k, v in c.items() if k in card_fields}
        row["set_code"] = c["set"]
        row.setdefault("set_id", None)
        rows.append(row)
        printings.append(
            {"id": c["id"], "card_id": c["id"], "is_base": True, "set_id": row["set_id"], "image_url": c.get("image"), "language": "en"}
        )
        for v in c.get("variants") or []:
            printings.append(
                {
                    "id": v["id"], "card_id": c["id"], "is_base": False, "set_id": v.get("set_id"),
                    "image_url": v.get("image"), "language": v.get("language", "en"),
                }
            )
    _upsert(db, Card, rows)
    _upsert(db, CardPrinting, printings)
    db.commit()
    return len(rows)


def upsert_card_names(db: Session, names: dict[str, str], language: str) -> int:
    """Saves each card's name in `language` ({card id: name}), for cards we have.

    Names for card numbers that aren't in `cards` (e.g. Japanese-only cards) are
    skipped. Returns how many were saved. Never deletes anything.
    """
    known = set(db.scalars(select(Card.id)))
    rows = [{"card_id": cid, "language": language, "name": name} for cid, name in names.items() if cid in known and name]
    for start in range(0, len(rows), 500):
        stmt = insert(CardName).values(rows[start : start + 500])
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=[CardName.card_id, CardName.language],
                set_={"name": stmt.excluded.name, "updated_at": func.now()},
            )
        )
    db.commit()
    return len(rows)


def load_card_names(db: Session, language: str) -> dict[str, list[str]]:
    """Each name in `language` and the ids of the cards with it, e.g. {"ナミ": ["OP01-016", ...]}."""
    by_name: dict[str, list[str]] = {}
    for card_id, name in db.execute(
        select(CardName.card_id, CardName.name).where(CardName.language == language).order_by(CardName.card_id)
    ):
        by_name.setdefault(name, []).append(card_id)
    return by_name
