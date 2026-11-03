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
from .models import Card


class CardStore:
    def __init__(self, cards: list[dict]) -> None:
        self.cards = sorted(cards, key=lambda c: c["id"])
        self.by_id: dict[str, dict] = {c["id"]: c for c in self.cards}
        self.json = json.dumps(self.cards, ensure_ascii=False, separators=(",", ":")).encode()
        # Changes whenever the card data changes, so browsers can cache it.
        self.etag = '"' + hashlib.sha256(self.json).hexdigest()[:16] + '"'

    def get(self, card_id: str) -> dict | None:
        return self.by_id.get(card_id.upper())


def load_cards(db: Session) -> list[dict]:
    return [card.to_dict() for card in db.scalars(select(Card).order_by(Card.id))]


@lru_cache(maxsize=1)
def _load_store() -> CardStore:
    with session_factory()() as db:
        return CardStore(load_cards(db))


def get_store() -> CardStore:
    """FastAPI dependency: the card list, loaded from the database the first time."""
    if database_url() is None:
        raise HTTPException(status_code=503, detail="Set DATABASE_URL in backend/.env to load cards.")
    return _load_store()


def reload_store() -> None:
    _load_store.cache_clear()


def upsert_cards(db: Session, cards: list[dict]) -> int:
    """Adds new cards and updates existing ones. Never deletes a card.

    Takes cards in the frontend shape (with "set"), as the import script builds them.
    """
    rows = [{**{k: v for k, v in c.items() if k != "set"}, "set_code": c["set"]} for c in cards]
    for start in range(0, len(rows), 500):
        chunk = rows[start : start + 500]
        stmt = insert(Card).values(chunk)
        updatable = {col: stmt.excluded[col] for col in chunk[0] if col != "id"}
        updatable["updated_at"] = func.now()
        db.execute(stmt.on_conflict_do_update(index_elements=[Card.id], set_=updatable))
    db.commit()
    return len(rows)
