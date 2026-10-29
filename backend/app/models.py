"""Database tables: the card list, decks, and the cards in each deck.

No names, emails or other personal details are stored. A deck belongs to an
"owner key", a random secret the app creates on the device; only a SHA-256
hash of that key is saved.

Cards are copied into our own `cards` table by scripts/import_cards.py, and
decks point at those rows with foreign keys. A deck never depends on the
outside data source: the import adds and updates cards but never deletes one,
and the database refuses to delete a card that any deck still uses.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20))
    colors: Mapped[list[str]] = mapped_column(JSONB, default=list)
    cost: Mapped[int | None] = mapped_column(Integer)
    life: Mapped[int | None] = mapped_column(Integer)
    power: Mapped[int | None] = mapped_column(Integer)
    counter: Mapped[int | None] = mapped_column(Integer)
    attributes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    types: Mapped[list[str]] = mapped_column(JSONB, default=list)
    effect: Mapped[str] = mapped_column(Text, default="")
    trigger: Mapped[str] = mapped_column(Text, default="")
    rarity: Mapped[str | None] = mapped_column(String(20))
    set_code: Mapped[str] = mapped_column(String(10), index=True)
    pack: Mapped[str | None] = mapped_column(String(100))
    block: Mapped[int | None] = mapped_column(Integer)
    image: Mapped[str | None] = mapped_column(Text)
    # Alternate arts, as [{"id": "OP01-001_p1", "image": "..."}]. Not used by decks yet.
    variants: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def to_dict(self) -> dict:
        """The shape the frontend uses (the set code is called "set" there)."""
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "colors": self.colors,
            "cost": self.cost,
            "life": self.life,
            "power": self.power,
            "counter": self.counter,
            "attributes": self.attributes,
            "types": self.types,
            "effect": self.effect,
            "trigger": self.trigger,
            "rarity": self.rarity,
            "set": self.set_code,
            "pack": self.pack,
            "block": self.block,
            "image": self.image,
            "variants": self.variants,
        }


class Deck(Base):
    __tablename__ = "decks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    owner_hash: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(100))
    leader_id: Mapped[str | None] = mapped_column(ForeignKey("cards.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    cards: Mapped[list[DeckCard]] = relationship(
        back_populates="deck", cascade="all, delete-orphan", order_by="DeckCard.card_id"
    )


class DeckCard(Base):
    __tablename__ = "deck_cards"
    __table_args__ = (CheckConstraint("count > 0", name="deck_cards_count_positive"),)

    deck_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("decks.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[str] = mapped_column(
        ForeignKey("cards.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    count: Mapped[int]

    deck: Mapped[Deck] = relationship(back_populates="cards")
