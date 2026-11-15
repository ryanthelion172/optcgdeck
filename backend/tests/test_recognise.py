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
    assert body["unmatched"][0]["closest"] == "OP01-016"


def test_closest_card_prefers_the_name_match():
    seen = {"imageMatch": {"card": "OP01-016", "score": 0.4}, "nameMatch": {"card": "OP01-013", "score": 0.5}}
    assert scan.closest(seen) == "OP01-013"
    assert scan.closest({"imageMatch": {"card": "OP01-016", "score": 0.4}}) == "OP01-016"
    assert scan.closest({"imageMatch": "image match off: run scripts/build_image_index.py"}) is None
    assert scan.closest({}) is None


def test_reads_the_printed_card_number():
    pytest.importorskip("rapidocr_onnxruntime")
    from app.ocr import read_number

    card = fake_card(1)
    h, w = card.shape[:2]
    cv2.rectangle(card, (0, int(h * 0.9)), (w, h), (240, 240, 240), -1)
    cv2.putText(card, "OP01-016 R", (int(w * 0.6), int(h * 0.97)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 1, cv2.LINE_AA)
    assert read_number(card, store)[0] == "OP01-016"
    assert read_number(cv2.rotate(card, cv2.ROTATE_180), store, upside_down=True)[0] == "OP01-016"


def test_unplaced_cards_say_when_the_image_index_is_missing():
    assert scan.describe({"setCodeRead": "", "imageMatch": "image match off: run scripts/build_image_index.py"}) == (
        "No number read; image match off: run scripts/build_image_index.py"
    )


def test_a_damaged_index_file_turns_image_match_off(tmp_path):
    from app.match import load_index

    bad = tmp_path / "index.npz"
    bad.write_bytes(b"not a real index")
    assert load_index(bad) is None


def test_big_photos_are_shrunk_before_reading():
    big = np.zeros((4000, 3000, 3), np.uint8)
    assert scan.shrink(big).shape[:2] == (880, 660)
    small = np.zeros((400, 300, 3), np.uint8)
    assert scan.shrink(small) is small


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Monkey.D.Luffy", "monkeydluffy"),
        ("Monkey.D.Lufy", "monkeydluffy"),  # a letter dropped
        ("Roronoa Zor0", "roronoazoro"),
        ("Prisoner of lmpel Down", "prisonerofimpeldown"),
        ("Straw Hat Crew", None),  # a types line, not a name
        ("Big Mom Pirate", None),
        ("2000", None),
        ("CHARACTER", None),
    ],
)
def test_names_are_matched_loosely(text, expected):
    from app.ocr import match_name

    found = match_name(text, store)
    assert (found[0] if found else None) == expected


def card_with_name(name: str) -> np.ndarray:
    card = fake_card(2)
    h, w = card.shape[:2]
    cv2.putText(card, name, (int(w * 0.12), int(h * 0.88)), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 2, cv2.LINE_AA)
    cv2.putText(card, "Straw Hat Crew", (int(w * 0.3), int(h * 0.93)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 1, cv2.LINE_AA)
    return card


def test_reads_the_card_name():
    pytest.importorskip("rapidocr_onnxruntime")
    from app.ocr import read_name

    card = card_with_name("Sanji")
    assert read_name(card, store)[0] == ["OP01-013"]
    assert read_name(cv2.rotate(card, cv2.ROTATE_180), store, upside_down=True)[0] == ["OP01-013"]
    assert sorted(read_name(card_with_name("Monkey.D.Luffy"), store)[0]) == ["OP05-119", "P-001", "ST01-001", "ST01-012"]


class FakeIndex:
    """Answers like ImageIndex.best: `weak` for the whole index, `named` within a name's cards."""

    def __init__(self, weak, named=None):
        self.weak, self.named, self.asked = weak, named, []

    def best(self, img, only=None):
        self.asked.append(only)
        return self.weak if only is None else self.named


def no_number(monkeypatch, name_ids):
    from app import ocr

    monkeypatch.setattr(ocr, "read_number", lambda img, store, upside_down=False: (None, ""))
    monkeypatch.setattr(ocr, "read_name", lambda img, store, upside_down=False: (name_ids, "name"))


def test_a_weak_art_match_falls_back_to_the_name(monkeypatch):
    from app.match import Match

    luffys = ["OP05-119", "P-001", "ST01-001", "ST01-012"]
    no_number(monkeypatch, luffys)
    index = FakeIndex(Match("OP01-016", 0.5, None, []), Match("ST01-012", 0.55, "Low", []))
    found, seen = scan.recognise_card(fake_card(3), store, index)
    assert index.asked == [None, set(luffys)]  # the art is compared with only the Luffys
    assert found == scan.local_detection("ST01-012", "Low", "name + image match")  # several Luffys: worth a look
    assert seen["nameRead"] == "name" and seen["nameMatch"]["card"] == "ST01-012"


def test_a_name_with_one_card_settles_it(monkeypatch):
    from app.match import Match

    no_number(monkeypatch, ["OP01-013"])
    index = FakeIndex(Match("OP01-016", 0.5, None, []), Match("OP01-013", 0.4, "Low", []))
    found, _ = scan.recognise_card(fake_card(3), store, index)
    assert found == scan.local_detection("OP01-013", "Medium", "name + image match")


def test_a_low_art_match_that_the_name_agrees_with_is_kept(monkeypatch):
    from app.match import Match

    no_number(monkeypatch, ["OP01-016"])
    index = FakeIndex(Match("OP01-016", 0.61, "Low", []))
    found, _ = scan.recognise_card(fake_card(3), store, index)
    assert found == scan.local_detection("OP01-016", "Medium", "name + image match")
    assert index.asked == [None]


def test_strong_art_matches_skip_the_name(monkeypatch):
    from app.match import Match

    no_number(monkeypatch, ["OP01-013"])
    index = FakeIndex(Match("OP01-016", 0.8, "High", []))
    found, seen = scan.recognise_card(fake_card(3), store, index)
    assert found["via"] == "image match" and "nameRead" not in seen


def test_no_name_read_keeps_a_low_art_match(monkeypatch):
    from app.match import Match

    no_number(monkeypatch, [])
    index = FakeIndex(Match("OP01-016", 0.61, "Low", []))
    found, seen = scan.recognise_card(fake_card(3), store, index)
    assert found == scan.local_detection("OP01-016", "Low", "image match")
    assert scan.describe(seen) == 'No number read; closest art OP01-016 (0.61); name read "name / name"'


def test_image_match_can_be_limited_to_some_cards():
    cards = [fake_card(i) for i in range(5)]
    index = ImageIndex([f"C{i}" for i in range(5)], np.stack([fingerprint(c) for c in cards]))
    m = index.best(photo_of(cards[1]), only={"C3", "C4"})
    assert m.card_id in {"C3", "C4"}
    assert index.best(photo_of(cards[1]), only={"nope"}) is None


def test_short_reads_must_match_exactly():
    from app.ocr import match_name

    assert match_name("Nami", store)[0] == "nami"
    assert match_name("Nmi", store) is None  # too short to trust a near miss


def test_a_types_line_is_not_taken_for_the_name():
    pytest.importorskip("rapidocr_onnxruntime")
    from app.ocr import read_name

    # "Impel Down" is both a type and a card name (OP16-042's name is "Prisoner of
    # Impel Down", and the sample has no card called "Impel Down", so add one).
    cards = [*SAMPLE_CARDS, {**SAMPLE_CARDS[0], "id": "OP99-001", "name": "Impel Down", "types": ["Impel Down"]}]
    with_type = CardStore(cards)
    card = fake_card(4)
    h, w = card.shape[:2]
    cv2.rectangle(card, (0, int(h * 0.7)), (w, h), (235, 235, 235), -1)
    effect = (int(w * 0.08), int(h * 0.76))
    cv2.putText(card, "Draw 1 card and trash 1 card.", effect, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 1, cv2.LINE_AA)
    types_line = (int(w * 0.33), int(h * 0.94))
    cv2.putText(card, "Impel Down", types_line, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 1, cv2.LINE_AA)
    # The name above it is unreadable (glare): the types line must not stand in for it.
    assert read_name(card, with_type)[0] == []
    # Printed name-sized, the same words are the card's name.
    cv2.putText(card, "Impel Down", (int(w * 0.2), int(h * 0.88)), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (20, 20, 20), 2, cv2.LINE_AA)
    assert read_name(card, with_type)[0] == ["OP99-001"]
