"""Deck endpoints, run against a real Postgres (see the `database` fixture)."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

KEY_A = "a" * 40
KEY_B = "b" * 40


@pytest.fixture
def client(database):
    from app.main import app

    return TestClient(app)


def put(client, deck_id, body, key=KEY_A):
    return client.put(f"/api/decks/{deck_id}", json=body, headers={"X-Owner-Key": key})


def test_save_load_update_delete(client):
    deck_id = str(uuid.uuid4())
    body = {"name": "Zoro", "leaderId": "OP01-001", "cards": {"OP01-016": 4, "OP01-013": 2}}
    saved = put(client, deck_id, body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["cards"] == {"OP01-013": 2, "OP01-016": 4}

    body["cards"] = {"OP01-016": 3}
    body["name"] = "Zoro v2"
    assert put(client, deck_id, body).json()["cards"] == {"OP01-016": 3}

    listed = client.get("/api/decks", headers={"X-Owner-Key": KEY_A}).json()
    mine = [d for d in listed if d["id"] == deck_id]
    assert mine and mine[0]["name"] == "Zoro v2"

    assert client.delete(f"/api/decks/{deck_id}", headers={"X-Owner-Key": KEY_A}).status_code == 204
    assert all(d["id"] != deck_id for d in client.get("/api/decks", headers={"X-Owner-Key": KEY_A}).json())


def test_other_owners_cannot_see_or_change_a_deck(client):
    deck_id = str(uuid.uuid4())
    put(client, deck_id, {"name": "Mine", "cards": {}})
    assert all(d["id"] != deck_id for d in client.get("/api/decks", headers={"X-Owner-Key": KEY_B}).json())
    assert put(client, deck_id, {"name": "Stolen", "cards": {}}, key=KEY_B).status_code == 404
    assert client.delete(f"/api/decks/{deck_id}", headers={"X-Owner-Key": KEY_B}).status_code == 404


def test_only_the_key_hash_is_stored(client):
    from sqlalchemy import text

    from app.db import get_engine

    put(client, str(uuid.uuid4()), {"name": "Hash check", "cards": {}})
    with get_engine().connect() as conn:
        stored = conn.execute(text("select owner_hash from decks where owner_id is null")).scalars().all()
    assert KEY_A not in stored
    assert all(len(h) == 64 for h in stored)


def test_rejects_unknown_cards_and_missing_key(client):
    assert put(client, str(uuid.uuid4()), {"name": "x", "cards": {"ZZ99-999": 1}}).status_code == 422
    assert client.get("/api/decks").status_code == 422
    assert client.get("/api/decks", headers={"X-Owner-Key": "short"}).status_code == 422


def test_simultaneous_first_saves_of_one_deck(client):
    deck_id = str(uuid.uuid4())
    bodies = [{"name": f"v{i}", "cards": {"OP01-016": (i % 4) + 1}} for i in range(8)]
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda b: put(client, deck_id, b).status_code, bodies))
    assert codes == [200] * 8
    decks = [d for d in client.get("/api/decks", headers={"X-Owner-Key": KEY_A}).json() if d["id"] == deck_id]
    assert len(decks) == 1
