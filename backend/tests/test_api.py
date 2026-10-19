from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_list_cards_has_leaders_and_etag():
    resp = client.get("/api/cards")
    assert resp.status_code == 200
    cards = resp.json()
    assert len(cards) > 1000
    assert any(c["category"] == "Leader" for c in cards)
    etag = resp.headers["etag"]
    assert client.get("/api/cards", headers={"If-None-Match": etag}).status_code == 304


def test_get_card_case_insensitive():
    card = client.get("/api/cards/op01-001").json()
    assert card["id"] == "OP01-001"
    assert card["category"] == "Leader"
    assert card["life"] is not None and card["cost"] is None


def test_unknown_card_404():
    assert client.get("/api/cards/XX99-999").status_code == 404
