"""The local steps of photo scanning: reading the card number and matching the art."""

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import main, scan
from app.cards import CardStore
from app.main import app
from app.match import ImageIndex, fingerprint
from app.ocr import candidates

from .conftest import SAMPLE_CARDS
from .photos import deck_photo

store = CardStore(SAMPLE_CARDS)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("OP01-016 R", ["OP01-016"]),
        ("0P01-O16", ["OP01-016"]),  # letters and digits mixed up
        ("OP 01 - 016", ["OP01-016"]),
        ("ST10-010 SR", ["ST10-010"]),
        ("PRB01-001", ["PRB01-001"]),
        ("P-001", ["P-001"]),
        ("2000 Straw Hat Crew", []),
    ],
)
def test_card_number_candidates(text, expected):
    assert candidates(text) == expected


def fake_card(seed: int, size=(630, 880)) -> np.ndarray:
    """A card-sized image with random shapes for 'art', different for each seed."""
    rng = np.random.default_rng(seed)
    w, h = size
    img = np.full((h, w, 3), rng.integers(0, 255, 3), np.uint8)
    for _ in range(25):
        color = tuple(int(c) for c in rng.integers(0, 255, 3))
        center = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        cv2.circle(img, center, int(rng.integers(20, 160)), color, -1)
    cv2.rectangle(img, (0, int(h * 0.65)), (w, h), (235, 235, 235), -1)  # text box
    return img


def photo_of(img: np.ndarray) -> np.ndarray:
    """The card as a phone might see it: a bit dim, blurry and warm."""
    out = cv2.GaussianBlur(img, (7, 7), 2).astype(np.float32)
    out = out * 0.75 + np.array([0, 10, 30])
    return np.clip(out, 0, 255).astype(np.uint8)


def test_image_match_finds_the_card_and_rejects_unknown_ones():
    cards = [fake_card(i) for i in range(30)]
    index = ImageIndex([f"C{i}" for i in range(20)], np.stack([fingerprint(c) for c in cards[:20]]))
    for i in range(20):
        m = index.best(photo_of(cards[i]))
        assert m.card_id == f"C{i}" and m.confidence is not None
        upside_down = index.best(cv2.rotate(photo_of(cards[i]), cv2.ROTATE_180))
        assert upside_down.card_id == f"C{i}"
    for card in cards[20:]:  # not in the index
        assert index.best(photo_of(card)).confidence is None


def test_alternate_arts_count_as_their_card():
    cards = [fake_card(i) for i in range(3)]
    index = ImageIndex(["C0", "C0", "C1"], np.stack([fingerprint(c) for c in cards]))
    assert index.best(photo_of(cards[1])).card_id == "C0"


def test_cards_found_locally_skip_cardsight(monkeypatch):
    calls = []

    def fake_identify(image, filename, mime):
        calls.append(filename)
        return [{"confidence": "High", "card": {"number": "OP01-001"}}]

    def fake_recognise(img, store, index):
        return scan.local_detection("OP01-016", "High", "set code"), {"setCodeRead": "OP01-016"}

    monkeypatch.setattr(main, "identify", fake_identify)
    monkeypatch.setattr(scan, "recognise_card", fake_recognise)
    body = TestClient(app).post("/api/scan", files={"photo": ("d.jpg", deck_photo(3), "image/jpeg")}).json()
    assert calls == []  # every card was read locally, so no API calls
    assert body["cards"] == [{"id": "OP01-016", "count": 3, "confidence": "High", "via": ["set code"]}]


def test_only_leftover_cards_go_to_cardsight(monkeypatch):
    calls = []

    def fake_identify(image, filename, mime):
        calls.append(filename)
        return [] if filename == "d.jpg" else [{"confidence": "Medium", "card": {"number": "OP01-001"}}]

    seen = iter(range(100))

    def fake_recognise(img, store, index):
        if next(seen) == 0:
            return scan.local_detection("OP01-016", "High", "image match"), {}
        return None, {"setCodeRead": "0P0l"}

    monkeypatch.setattr(main, "identify", fake_identify)
    monkeypatch.setattr(scan, "PARALLEL_CALLS", 1)  # keep the order
    monkeypatch.setattr(scan, "recognise_card", fake_recognise)
    body = TestClient(app).post("/api/scan", files={"photo": ("d.jpg", deck_photo(3), "image/jpeg")}).json()
    assert sorted(calls) == ["card-2.jpg", "card-3.jpg", "d.jpg"]
    assert {"id": "OP01-016", "count": 1, "confidence": "High", "via": ["image match"]} in body["cards"]
    assert {"id": "OP01-001", "count": 2, "confidence": "Medium", "via": ["CardSight"]} in body["cards"]


def test_unplaced_cards_say_what_was_read(monkeypatch):
    monkeypatch.setattr(main, "identify", lambda *a: [])
    monkeypatch.setattr(
        scan, "recognise_card",
        lambda img, store, index: (None, {"setCodeRead": "OP0", "imageMatch": {"card": "OP01-016", "score": 0.41}}),
    )
    body = TestClient(app).post("/api/scan", files={"photo": ("d.jpg", deck_photo(2), "image/jpeg")}).json()
    assert body["unmatched"][0]["detail"] == 'Read "OP0"; closest art OP01-016 (0.41)'


def test_reads_the_printed_card_number():
    pytest.importorskip("rapidocr_onnxruntime")
    from app.ocr import read_number

    card = fake_card(1)
    h, w = card.shape[:2]
    cv2.rectangle(card, (0, int(h * 0.9)), (w, h), (240, 240, 240), -1)
    cv2.putText(card, "OP01-016 R", (int(w * 0.6), int(h * 0.97)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 1, cv2.LINE_AA)
    assert read_number(card, store)[0] == "OP01-016"
    assert read_number(cv2.rotate(card, cv2.ROTATE_180), store, upside_down=True)[0] == "OP01-016"
