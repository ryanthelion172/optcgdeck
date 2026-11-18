import pytest
from fastapi.testclient import TestClient

from app import scan
from app.main import app

from .photos import blank_photo, deck_photo, single_card_photo


def recognise_in_turn(monkeypatch, answers):
    """Makes the local steps return `answers` in order: a card id, or None for a card they can't place."""
    answers = iter(answers)

    def fake(img, store, index):
        card_id = next(answers)
        return (scan.detection(card_id, "High", "set code"), {}) if card_id else (None, {"setCodeRead": ""})

    monkeypatch.setattr(scan, "PARALLEL_CALLS", 1)  # keep the answers in order
    monkeypatch.setattr(scan, "recognise_card", fake)


def post(photo, filename="deck.jpg", mode=None):
    data = {"mode": mode} if mode else None
    resp = TestClient(app).post("/api/scan", files={"photo": (filename, photo, "image/jpeg")}, data=data)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_count_cards_groups_copies():
    found = [
        scan.detection("OP01-016", "High", "set code"),
        scan.detection("OP01-016", "Low", "image match"),
        scan.detection("OP01-001", "High", "set code"),
    ]
    assert scan.count_cards(found) == [
        {"id": "OP01-016", "count": 2, "confidence": "Low", "via": ["set code", "image match"]},
        {"id": "OP01-001", "count": 1, "confidence": "High", "via": ["set code"]},
    ]


def test_scan_rejects_non_images():
    resp = TestClient(app).post("/api/scan", files={"photo": ("x.txt", b"hi", "text/plain")})
    assert resp.status_code == 400
    resp = TestClient(app).post("/api/scan", files={"photo": ("x.jpg", b"not really", "image/jpeg")})
    assert resp.status_code == 400


def test_scan_rejects_unknown_modes():
    resp = TestClient(app).post(
        "/api/scan", files={"photo": ("d.jpg", blank_photo(), "image/jpeg")}, data={"mode": "binder"}
    )
    assert resp.status_code == 422


def test_scan_identifies_each_card_found(monkeypatch):
    recognise_in_turn(monkeypatch, ["OP01-016", "OP01-013", "OP01-001", "OP01-016", None, "OP01-025"])
    body = post(deck_photo(6))
    assert body["cardsFound"] == body["detected"] == 6
    assert {"id": "OP01-016", "count": 2, "confidence": "High", "via": ["set code"]} in body["cards"]
    assert {"id": "OP01-001", "count": 1, "confidence": "High", "via": ["set code"]} in body["cards"]
    assert len(body["unmatched"]) == 1
    missed = body["unmatched"][0]
    assert missed["label"] == "Card 5 in the photo (not recognised)"
    assert missed["image"].startswith("data:image/jpeg;base64,")  # the crop, so the app can show it
    assert len(body["raw"]["cards"]) == 6 and len(body["raw"]["cards"][0]["corners"]) == 4


def test_a_photo_with_no_card_outlines_is_read_as_one_card(monkeypatch):
    recognise_in_turn(monkeypatch, ["OP01-016"])
    body = post(blank_photo())
    assert body["cards"] == [{"id": "OP01-016", "count": 1, "confidence": "High", "via": ["set code"]}]
    assert body["cardsFound"] == 0


def test_deck_scan_of_one_close_up_card_uses_the_whole_photo(monkeypatch):
    """One outline found but not recognised, while the whole photo is: no 'not recognised' row."""
    recognise_in_turn(monkeypatch, [None, None, "OP01-016"])  # deck crop, single crop, whole photo
    body = post(single_card_photo(), "card.jpg")
    assert body["cards"] == [{"id": "OP01-016", "count": 1, "confidence": "High", "via": ["set code"]}]
    assert body["unmatched"] == []


def test_single_card_scan_tries_the_crop_then_the_whole_photo(monkeypatch):
    recognise_in_turn(monkeypatch, ["OP01-016"])
    body = post(single_card_photo(), "card.jpg", mode="single")
    assert body["cards"] == [{"id": "OP01-016", "count": 1, "confidence": "High", "via": ["set code"]}]
    assert body["detected"] == body["cardsFound"] == 1 and body["unmatched"] == []

    recognise_in_turn(monkeypatch, [None, "OP01-001"])
    body = post(single_card_photo(), "card.jpg", mode="single")
    assert [c["id"] for c in body["cards"]] == ["OP01-001"]


@pytest.mark.parametrize("photo, crop", [(blank_photo, False), (single_card_photo, True)])
def test_single_card_scan_reports_an_unrecognised_card(monkeypatch, photo, crop):
    recognise_in_turn(monkeypatch, [None, None])
    body = post(photo(), "card.jpg", mode="single")
    assert body["cards"] == []
    assert body["unmatched"][0]["label"].startswith("The card")
    assert ("image" in body["unmatched"][0]) == crop
