"""The cards table: loading, importing and the links from decks."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.cards import get_store, load_printings, reload_store, upsert_cards
from app.main import app
from app.models import Card, CardPrinting

from .conftest import SAMPLE_CARDS, SAMPLE_DB_CARDS

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
    expected = next(c for c in SAMPLE_CARDS if c["id"] == "OP01-016")
    assert nami == {k: v for k, v in expected.items() if k != "variants"}  # base art only
    assert all("variants" not in c for c in cards)


def test_alternate_arts_are_kept_for_scanning(database):
    with database.session_factory()() as db:
        printings = load_printings(db)
    zoro = [p for p in printings if p["card_id"] == "OP01-001"]
    assert [(p["id"], p["is_base"]) for p in zoro] == [("OP01-001", True), ("OP01-001_p1", False), ("OP01-001_p2", False)]
    assert all(p["image"] for p in zoro)


def test_import_updates_cards_and_never_deletes(database):
    with database.session_factory()() as db:
        changed = {**SAMPLE_DB_CARDS[0], "name": "Renamed by the source"}
        upsert_cards(db, [changed])  # a later import that only has one card
        assert db.get(Card, changed["id"]).name == "Renamed by the source"
        assert len(db.scalars(select(Card.id)).all()) == len(SAMPLE_CARDS)
        upsert_cards(db, [SAMPLE_DB_CARDS[0]])  # put it back


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


def test_decks_can_belong_to_a_user(database):
    from sqlalchemy.exc import IntegrityError as Integrity

    from app.models import Deck, User

    with database.session_factory()() as db:
        user = User(email="Tester@Example.com")
        db.add(user)
        db.flush()
        db.add(Deck(id=uuid.uuid4(), owner_id=user.id, name="Account deck"))
        db.commit()
        assert [d.name for d in user.decks] == ["Account deck"]

        db.add(User(email="tester@example.com"))  # same email, other case
        with pytest.raises(Integrity):
            db.commit()
        db.rollback()

        db.add(Deck(id=uuid.uuid4(), name="Nobody's"))  # no owner at all
        with pytest.raises(Integrity):
            db.commit()
        db.rollback()

        db.delete(db.get(User, user.id))  # deleting an account deletes its decks
        db.commit()
        assert db.scalars(select(Deck).where(Deck.name == "Account deck")).all() == []


def test_japanese_names_are_saved_by_card_number(database):
    from app.cards import load_card_names, upsert_card_names
    from app.models import CardName

    names = {"OP01-016": "ナミ", "OP01-013": "サンジ", "OP99-001": "日本だけのカード"}  # the last isn't in English
    with database.session_factory()() as db:
        assert upsert_card_names(db, names, "ja") == 2
        assert upsert_card_names(db, {"OP01-016": "ナミ（新）"}, "ja") == 1  # a later import updates it
        assert load_card_names(db, "ja") == {"ナミ（新）": ["OP01-016"], "サンジ": ["OP01-013"]}
        assert load_card_names(db, "fr") == {}
        db.execute(delete(CardName))
        db.commit()


def test_printings_remember_which_regions_list_they_came_from(database):
    with database.session_factory()() as db:
        card = {**SAMPLE_DB_CARDS[2], "variants": [{"id": "OP01-016_p9", "image": "https://asia-en.example/p9.png", "language": "en-asia"}]}
        upsert_cards(db, [card])
        by_id = {p["id"]: p for p in load_printings(db) if p["card_id"] == "OP01-016"}
        assert by_id["OP01-016"]["language"] == "en"
        assert by_id["OP01-016_p9"]["language"] == "en-asia"
        db.execute(delete(CardPrinting).where(CardPrinting.id == "OP01-016_p9"))
        db.commit()
