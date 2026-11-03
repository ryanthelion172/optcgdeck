import httpx
import pytest
from fastapi.testclient import TestClient

from app import main, scan
from app.cards import CardStore
from app.main import app

from .conftest import SAMPLE_CARDS
from .photos import blank_photo, deck_photo, single_card_photo

store = CardStore(SAMPLE_CARDS)


def det(name=None, number=None, release=None, confidence="High"):
    card = {k: v for k, v in {"name": name, "number": number, "releaseName": release}.items() if v}
    return {"confidence": confidence, "card": card}


@pytest.mark.parametrize(
    "card, expected",
    [
        ({"number": "OP01-016", "name": "Nami"}, "OP01-016"),
        ({"number": "op01016"}, "OP01-016"),
        ({"number": "016", "releaseName": "Romance Dawn [OP-01]"}, "OP01-016"),
        ({"number": "001", "setName": "ST01 Straw Hat Crew"}, "ST01-001"),
        ({"name": "Nonexistent Pirate"}, None),
        ({}, None),
    ],
)
def test_match_card(card, expected):
    assert scan.match_card(card, store) == expected


def test_build_result_groups_copies_and_keeps_unmatched():
    result = scan.build_result(
        [
            det(number="OP01-016"),
            det(number="OP01-016", confidence="Low"),
            det(number="OP01-001"),
            det(name="Mystery Card", number="999"),
        ],
        store,
    )
    assert result["detected"] == 4
    assert {"id": "OP01-016", "count": 2, "confidence": "Low"} in result["cards"]
    assert {"id": "OP01-001", "count": 1, "confidence": "High"} in result["cards"]
    assert result["unmatched"] == [{"label": "Mystery Card · 999", "confidence": "High"}]


def test_identify_sends_named_file_and_parses_response(monkeypatch):
    """Runs the real SDK call with the network replaced by a fake response."""
    monkeypatch.setenv("CARDSIGHTAI_API_KEY", "test-key")
    sent = {}

    def fake_request(self, method, url, **kwargs):
        sent["url"] = url
        sent["files"] = kwargs.get("files")
        payload = {
            "success": True,
            "requestId": "r1",
            "detections": [
                {"confidence": "High", "card": {"name": "Nami", "number": "OP01-016"}},
            ],
        }
        return httpx.Response(200, json=payload, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    detections = scan.identify(b"\xff\xd8jpeg", "deck.jpg", "image/jpeg")

    assert sent["url"].endswith("/v1/identify/card/onepiece")
    image_part = dict(sent["files"])["image"]
    assert (image_part[0], image_part[2]) == ("deck.jpg", "image/jpeg")
    assert len(detections) == 1
    assert detections[0]["confidence"] == "High"
    assert scan.match_card(detections[0]["card"], store) == "OP01-016"


def test_scan_sends_the_whole_photo_when_no_cards_are_found(monkeypatch):
    calls = []
    photo = blank_photo()

    def fake_identify(image, filename, mime):
        calls.append((image, filename, mime))
        return [det(number="OP01-016"), det(number="OP01-016")]

    monkeypatch.setattr(main, "identify", fake_identify)
    resp = TestClient(app).post("/api/scan", files={"photo": ("deck.jpg", photo, "image/jpeg")})
    assert resp.status_code == 200
    assert resp.json()["cards"] == [{"id": "OP01-016", "count": 2, "confidence": "High"}]
    assert calls == [(photo, "deck.jpg", "image/jpeg")]


def test_scan_rejects_non_images():
    resp = TestClient(app).post("/api/scan", files={"photo": ("x.txt", b"hi", "text/plain")})
    assert resp.status_code == 400
    resp = TestClient(app).post("/api/scan", files={"photo": ("x.jpg", b"not really", "image/jpeg")})
    assert resp.status_code == 400


def test_scan_without_api_key(monkeypatch):
    monkeypatch.delenv("CARDSIGHTAI_API_KEY", raising=False)
    resp = TestClient(app).post("/api/scan", files={"photo": ("deck.jpg", blank_photo(), "image/jpeg")})
    assert resp.status_code == 503
    assert "CARDSIGHTAI_API_KEY" in resp.json()["detail"]


def test_scan_endpoint_includes_raw_detections(monkeypatch):
    raw = [det(name="Mystery", number="999")]
    monkeypatch.setattr(main, "identify", lambda *a: raw)
    resp = TestClient(app).post("/api/scan", files={"photo": ("deck.jpg", blank_photo(), "image/jpeg")})
    assert resp.json()["raw"]["wholePhoto"]["detections"] == raw


def test_scan_identifies_each_card_found(monkeypatch):
    """Six cards in the photo: six calls, one per cropped card."""
    answers = iter(["OP01-016", "OP01-013", "OP01-001", "OP01-016", None, "OP01-025"])
    calls = []

    def fake_identify(image, filename, mime):
        if filename == "deck.jpg":
            return []  # the whole-photo call finds nothing extra here
        calls.append((filename, mime))
        number = next(answers)
        if number is None:
            return []  # CardSight didn't recognise this one
        return [det(number=number, confidence="Low"), det(number=number, confidence="High")]

    monkeypatch.setattr(main, "identify", fake_identify)
    monkeypatch.setattr(scan, "PARALLEL_CALLS", 1)  # keep the answers in order
    resp = TestClient(app).post("/api/scan", files={"photo": ("deck.jpg", deck_photo(6), "image/jpeg")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(calls) == 6 and all(m == "image/jpeg" for _, m in calls)
    assert body["cardsFound"] == body["detected"] == 6
    assert {"id": "OP01-016", "count": 2, "confidence": "High"} in body["cards"]
    assert {"id": "OP01-001", "count": 1, "confidence": "High"} in body["cards"]
    assert body["unmatched"] == [{"label": "Card 5 in the photo (not recognised)", "confidence": "Low"}]
    assert len(body["raw"]["cards"]) == 6 and len(body["raw"]["cards"][0]["corners"]) == 4


def test_scan_keeps_going_when_some_cards_fail(monkeypatch):
    def flaky(image, filename, mime):
        if filename == "d.jpg":
            return []
        if filename == "card-2.jpg":
            raise scan.ScanError("timeout")
        return [det(number="OP01-016")]

    monkeypatch.setattr(main, "identify", flaky)
    body = TestClient(app).post("/api/scan", files={"photo": ("d.jpg", deck_photo(3), "image/jpeg")}).json()
    assert body["cards"] == [{"id": "OP01-016", "count": 2, "confidence": "High"}]
    assert body["unmatched"][0]["label"].startswith("Card 2")


def test_whole_photo_adds_cards_the_crops_missed(monkeypatch):
    def fake(image, filename, mime):
        if filename == "deck.jpg":  # the whole photo
            return [det(number="OP01-016"), det(number="OP01-001")]
        return [det(number="OP01-016")]

    monkeypatch.setattr(main, "identify", fake)
    body = TestClient(app).post("/api/scan", files={"photo": ("deck.jpg", deck_photo(2), "image/jpeg")}).json()
    assert body["cards"] == [
        {"id": "OP01-016", "count": 2, "confidence": "High"},  # from the two crops
        {"id": "OP01-001", "count": 1, "confidence": "High"},  # only the whole photo saw it
    ]


def test_single_card_scan_keeps_the_most_confident_answer(monkeypatch):
    calls = []

    def fake(image, filename, mime):
        calls.append(filename)
        if filename == "card.jpg":  # the whole photo
            return [det(number="OP01-001", confidence="Low")]
        return [det(number="OP01-016", confidence="Medium")]

    monkeypatch.setattr(main, "identify", fake)
    resp = TestClient(app).post(
        "/api/scan", files={"photo": ("card.jpg", single_card_photo(), "image/jpeg")}, data={"mode": "single"}
    )
    body = resp.json()
    assert sorted(calls) == ["card-1.jpg", "card.jpg"]
    assert body["cards"] == [{"id": "OP01-016", "count": 1, "confidence": "Medium"}]
    assert body["detected"] == body["cardsFound"] == 1
    assert body["unmatched"] == []


def test_single_card_scan_falls_back_to_the_whole_photo(monkeypatch):
    def fake(image, filename, mime):
        return [det(number="OP01-016")] if filename == "card.jpg" else []

    monkeypatch.setattr(main, "identify", fake)
    body = TestClient(app).post(
        "/api/scan", files={"photo": ("card.jpg", single_card_photo(), "image/jpeg")}, data={"mode": "single"}
    ).json()
    assert body["cards"] == [{"id": "OP01-016", "count": 1, "confidence": "High"}]


def test_single_card_scan_reports_an_unrecognised_card(monkeypatch):
    monkeypatch.setattr(main, "identify", lambda *a: [])
    body = TestClient(app).post(
        "/api/scan", files={"photo": ("card.jpg", blank_photo(), "image/jpeg")}, data={"mode": "single"}
    ).json()
    assert body["cards"] == [] and body["cardsFound"] == 0
    assert body["unmatched"][0]["label"].startswith("The card")


def test_scan_rejects_unknown_modes():
    resp = TestClient(app).post(
        "/api/scan", files={"photo": ("d.jpg", blank_photo(), "image/jpeg")}, data={"mode": "binder"}
    )
    assert resp.status_code == 422


def test_deck_scan_of_one_close_up_card_uses_the_whole_photo(monkeypatch):
    """One outline found but not recognised, while the whole photo is: no 'not recognised' row."""

    def fake(image, filename, mime):
        return [det(number="OP01-016")] if filename == "card.jpg" else []

    monkeypatch.setattr(main, "identify", fake)
    body = TestClient(app).post("/api/scan", files={"photo": ("card.jpg", single_card_photo(), "image/jpeg")}).json()
    assert body["cards"] == [{"id": "OP01-016", "count": 1, "confidence": "High"}]
    assert body["unmatched"] == []
