"""The cards table: loading, importing and the links from decks."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.cards import get_store, reload_store, upsert_cards
from app.main import app
from app.models import Card

from .conftest import SAMPLE_CARDS

KEY = "c" * 40


@pytest.fixture
def real_store(database):
    """Serve cards from the database instead of the sample list."""
    app.dependency_overrides.pop(get_store, None)
    reload_store()
    yield
    reload_store()


def test_cards_are_served_from_the_database(real_store):
    cards = TestClient(app).get("/api/cards").json()
    assert [c["id"] for c in cards] == sorted(c["id"] for c in SAMPLE_CARDS)
    nami = next(c for c in cards if c["id"] == "OP01-016")
    assert nami == next(c for c in SAMPLE_CARDS if c["id"] == "OP01-016")


def test_import_updates_cards_and_never_deletes(database):
    with database.session_factory()() as db:
        changed = {**SAMPLE_CARDS[0], "name": "Renamed by the source"}
        upsert_cards(db, [changed])  # a later import that only has one card
        assert db.get(Card, changed["id"]).name == "Renamed by the source"
        assert len(db.scalars(select(Card.id)).all()) == len(SAMPLE_CARDS)
        upsert_cards(db, [SAMPLE_CARDS[0]])  # put it back


def test_a_card_in_a_deck_cannot_be_deleted(database):
    client = TestClient(app)
    deck_id = str(uuid.uuid4())
    body = {"name": "Locked", "leaderId": "OP01-001", "cards": {"OP01-016": 4}}
    assert client.put(f"/api/decks/{deck_id}", json=body, headers={"X-Owner-Key": KEY}).status_code == 200

    for card_id in ("OP01-016", "OP01-001"):  # a deck card and a Leader
        with database.session_factory()() as db:
            with pytest.raises(IntegrityError):
                db.execute(delete(Card).where(Card.id == card_id))
                db.commit()

    deck = next(d for d in client.get("/api/decks", headers={"X-Owner-Key": KEY}).json() if d["id"] == deck_id)
    assert deck["cards"] == {"OP01-016": 4}
    assert client.delete(f"/api/decks/{deck_id}", headers={"X-Owner-Key": KEY}).status_code == 204
