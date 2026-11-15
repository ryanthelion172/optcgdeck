"""Database tables: sets, cards and their printings, users, decks, and the cards in each deck.

Card data is copied into our own tables by scripts/import_cards.py, and decks
point at those rows with foreign keys. A deck never depends on the outside
data source: the import adds and updates cards but never deletes one, and the
database refuses to delete a card that any deck still uses.

- `sets`: each product cards come in (booster packs, starter decks, promos).
- `cards`: one row per card number (e.g. OP01-016), with its game text.
  Decks use these.
- `card_printings`: every printed version of a card, the base art and each
  alternate art (e.g. OP01-016_p1), with its image. Only the backend uses
  them (photo scanning); the app is sent base arts only.
- `card_names`: each card's name in other languages (e.g. Japanese), keyed by
  card number, so a name read off a Japanese card can be looked up.
- `users`: accounts. A deck belongs to a user (`owner_id`), or, for decks made
  without an account, to an "owner key": a random secret the app creates on
  the device, of which only a SHA-256 hash is saved.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Set(Base):
    __tablename__ = "sets"

    # The source's pack id, e.g. "569101".
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    code: Mapped[str] = mapped_column(String(30))  # as printed, e.g. "OP-01", "ST-01", "OP15-EB04"
    name: Mapped[str | None] = mapped_column(String(200))  # e.g. "Romance Dawn"
    kind: Mapped[str | None] = mapped_column(String(50))  # e.g. "BOOSTER PACK", "STARTER DECK"
    release_date: Mapped[date | None] = mapped_column(Date)  # not in the source yet
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


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
    # From the card number: "OP01" from "OP01-016", "P" for promos.
    set_code: Mapped[str] = mapped_column(String(10), index=True)
    # The set the base art first came out in.
    set_id: Mapped[str | None] = mapped_column(ForeignKey("sets.id", ondelete="SET NULL"), index=True)
    block: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    set: Mapped[Set | None] = relationship(lazy="joined")
    printings: Mapped[list[CardPrinting]] = relationship(
        back_populates="card", order_by="CardPrinting.id", lazy="selectin"
    )

    @property
    def base_image(self) -> str | None:
        return next((p.image_url for p in self.printings if p.is_base), None)

    def to_dict(self) -> dict:
        """The shape the frontend uses: base art only (the set code is called "set" there)."""
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
            "pack": self.set.code if self.set else None,
            "block": self.block,
            "image": self.base_image,
        }


class CardPrinting(Base):
    """One printed version of a card: its base art or an alternate art."""

    __tablename__ = "card_printings"
    __table_args__ = (
        # At most one base art per card.
        Index("uq_card_printings_one_base", "card_id", unique=True, postgresql_where="is_base"),
    )

    id: Mapped[str] = mapped_column(String(30), primary_key=True)  # "OP01-016", "OP01-016_p1"
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    is_base: Mapped[bool] = mapped_column(Boolean, default=False)
    set_id: Mapped[str | None] = mapped_column(ForeignKey("sets.id", ondelete="SET NULL"))
    image_url: Mapped[str | None] = mapped_column(Text)
    # Which region's card list it came from: "en" (North America/Europe), or for
    # printings only listed elsewhere "en-asia", "ja", "zh-hk", "zh-tw", "th", "fr".
    language: Mapped[str] = mapped_column(String(10), default="en", server_default="en")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    card: Mapped[Card] = relationship(back_populates="printings")


class CardName(Base):
    """A card's name in another language. Card numbers are the same in every
    language, so the English card and its Japanese name share `card_id`."""

    __tablename__ = "card_names"

    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True)
    language: Mapped[str] = mapped_column(String(10), primary_key=True)  # "ja"
    name: Mapped[str] = mapped_column(String(200), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    """An account. Sign-up and sign-in aren't built yet; this is the table they'll use."""

    __tablename__ = "users"
    __table_args__ = (
        # Emails are unique regardless of case.
        Index("uq_users_email_lower", func.lower("email"), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(100))
    # None for accounts that sign in another way (e.g. Google), if that's added.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    decks: Mapped[list[Deck]] = relationship(back_populates="owner", cascade="all, delete-orphan", passive_deletes=True)


class Deck(Base):
    __tablename__ = "decks"
    __table_args__ = (
        CheckConstraint("owner_id IS NOT NULL OR owner_hash IS NOT NULL", name="decks_have_an_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # The deck's owner: a user account, or for decks made without one, the owner key's hash.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    owner_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(100))
    leader_id: Mapped[str | None] = mapped_column(ForeignKey("cards.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped[User | None] = relationship(back_populates="decks")
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
