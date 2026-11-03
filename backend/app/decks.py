"""Save and load decks in the database."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .cards import CardStore, get_store
from .db import get_session
from .models import Deck, DeckCard

router = APIRouter(prefix="/api/decks", tags=["decks"])


class DeckIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    leaderId: str | None = Field(default=None, max_length=20)
    cards: dict[str, int] = Field(default_factory=dict, max_length=200)


class DeckOut(DeckIn):
    id: uuid.UUID
    updatedAt: datetime


def owner_hash(x_owner_key: str = Header(min_length=32, max_length=128)) -> str:
    """The app sends its owner key in the X-Owner-Key header; we only keep its hash."""
    return hashlib.sha256(x_owner_key.encode()).hexdigest()


def to_out(deck: Deck) -> DeckOut:
    return DeckOut(
        id=deck.id,
        name=deck.name,
        leaderId=deck.leader_id,
        cards={c.card_id: c.count for c in deck.cards},
        updatedAt=deck.updated_at,
    )


def check_cards(body: DeckIn, store: CardStore) -> None:
    if body.leaderId and not store.get(body.leaderId):
        raise HTTPException(status_code=422, detail=f"Unknown card {body.leaderId}")
    for card_id, count in body.cards.items():
        if not store.get(card_id):
            raise HTTPException(status_code=422, detail=f"Unknown card {card_id}")
        if not 1 <= count <= 50:
            raise HTTPException(status_code=422, detail=f"Bad count for {card_id}")


@router.get("")
def list_decks(owner: str = Depends(owner_hash), db: Session = Depends(get_session)) -> list[DeckOut]:
    decks = db.scalars(
        select(Deck).where(Deck.owner_hash == owner).options(selectinload(Deck.cards)).order_by(Deck.updated_at.desc())
    )
    return [to_out(d) for d in decks]


@router.put("/{deck_id}")
def save_deck(
    deck_id: uuid.UUID,
    body: DeckIn,
    owner: str = Depends(owner_hash),
    db: Session = Depends(get_session),
    store: CardStore = Depends(get_store),
) -> DeckOut:
    """Creates or replaces a deck. Uses the deck id the app already generated."""
    check_cards(body, store)
    try:
        return _save(deck_id, body, owner, db)
    except IntegrityError:
        # Two first-time saves of the same new deck raced; the other one created
        # the row, so save again as an update.
        db.rollback()
        return _save(deck_id, body, owner, db)


def _save(deck_id: uuid.UUID, body: DeckIn, owner: str, db: Session) -> DeckOut:
    # Lock the row so two saves of the same deck at once can't interleave.
    deck = db.scalars(
        select(Deck).where(Deck.id == deck_id).options(selectinload(Deck.cards)).with_for_update()
    ).first()
    if deck is None:
        deck = Deck(id=deck_id, owner_hash=owner)
        db.add(deck)
    elif deck.owner_hash != owner:
        raise HTTPException(status_code=404, detail="Deck not found")

    deck.name = body.name
    deck.leader_id = body.leaderId and body.leaderId.upper()
    deck.cards = [DeckCard(card_id=cid.upper(), count=n) for cid, n in sorted(body.cards.items())]
    db.commit()
    db.refresh(deck)
    return to_out(deck)


@router.delete("/{deck_id}", status_code=204)
def delete_deck(deck_id: uuid.UUID, owner: str = Depends(owner_hash), db: Session = Depends(get_session)) -> Response:
    deck = db.get(Deck, deck_id)
    if deck is None or deck.owner_hash != owner:
        raise HTTPException(status_code=404, detail="Deck not found")
    db.delete(deck)
    db.commit()
    return Response(status_code=204)
