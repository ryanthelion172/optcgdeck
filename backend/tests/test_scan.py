import httpx
import pytest
from fastapi.testclient import TestClient

from app import main, scan
from app.cards import get_store
from app.main import app

store = get_store()


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


def test_scan_endpoint(monkeypatch):
    calls = []

    def fake_identify(image, filename, mime):
        calls.append((image, filename, mime))
        return [det(number="OP01-016"), det(number="OP01-016")]

    monkeypatch.setattr(main, "identify", fake_identify)
    resp = TestClient(app).post("/api/scan", files={"photo": ("deck.jpg", b"img", "image/jpeg")})
    assert resp.status_code == 200
    assert resp.json()["cards"] == [{"id": "OP01-016", "count": 2, "confidence": "High"}]
    assert calls == [(b"img", "deck.jpg", "image/jpeg")]


def test_scan_rejects_non_images():
    resp = TestClient(app).post("/api/scan", files={"photo": ("x.txt", b"hi", "text/plain")})
    assert resp.status_code == 400


def test_scan_without_api_key(monkeypatch):
    monkeypatch.delenv("CARDSIGHTAI_API_KEY", raising=False)
    resp = TestClient(app).post("/api/scan", files={"photo": ("deck.jpg", b"img", "image/jpeg")})
    assert resp.status_code == 503
    assert "CARDSIGHTAI_API_KEY" in resp.json()["detail"]


def test_scan_endpoint_includes_raw_detections(monkeypatch):
    raw = [det(name="Mystery", number="999")]
    monkeypatch.setattr(main, "identify", lambda *a: raw)
    resp = TestClient(app).post("/api/scan", files={"photo": ("deck.jpg", b"img", "image/jpeg")})
    assert resp.json()["raw"] == raw
