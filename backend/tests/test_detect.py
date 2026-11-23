import cv2
import numpy as np
import pytest

from app.detect import CROP_SIZE, BadImage, card_sized_rectangles, check_card_size, find_cards

from .photos import blank_photo, deck_photo, single_card_photo, stack_photo


def test_finds_every_card_in_reading_order():
    cards = find_cards(deck_photo(6))
    assert len(cards) == 6
    lefts = [c.corners[0][0] for c in cards[:4]]
    assert lefts == sorted(lefts)  # first row, left to right
    assert cards[4].corners[0][1] > cards[0].corners[0][1]  # second row is lower


def test_crops_are_upright_card_images():
    for card in find_cards(deck_photo(3, rotate_last=True)):
        img = cv2.imdecode(np.frombuffer(card.jpeg, np.uint8), cv2.IMREAD_COLOR)
        assert (img.shape[1], img.shape[0]) == CROP_SIZE


def test_works_on_a_light_background():
    assert len(find_cards(deck_photo(5, background=(235, 235, 235)))) == 5


def test_small_screenshots():
    img = cv2.imdecode(np.frombuffer(deck_photo(8), np.uint8), cv2.IMREAD_COLOR)
    small = cv2.resize(img, (300, 400), interpolation=cv2.INTER_AREA)
    assert len(find_cards(cv2.imencode(".jpg", small)[1].tobytes())) == 8


def test_no_cards_in_a_plain_photo():
    assert find_cards(blank_photo()) == []


def test_rejects_files_that_are_not_images():
    with pytest.raises(BadImage):
        find_cards(b"not an image")


def card_share(card, size=(1600, 1200)) -> float:
    h, w = size
    corners = (np.array(card.corners) * [w, h]).astype(np.float32)
    return cv2.contourArea(corners) / (w * h)


@pytest.mark.parametrize("fill", [0.4, 0.75, 0.92])
def test_one_card_photo_crops_the_whole_card(fill):
    """The card's outer edge is found, not its art or text box inside."""
    expected = (fill * 1600) * (fill * 1600 * 63 / 88) / (1600 * 1200)
    for single in (False, True):
        cards = find_cards(single_card_photo(fill), single=single)
        assert len(cards) == 1
        assert card_share(cards[0]) == pytest.approx(expected, rel=0.05)


def test_single_mode_finds_a_card_running_off_the_photo():
    assert len(find_cards(single_card_photo(1.1), single=True)) == 1


def test_single_mode_returns_at_most_one_card():
    assert len(find_cards(deck_photo(6), single=True)) == 1


def cut_photo(photo: bytes, keep_h: int | None = None, keep_w: int | None = None) -> tuple[bytes, tuple[int, int]]:
    """The photo cut short at the bottom and/or right, as if the camera missed part of the table."""
    img = cv2.imdecode(np.frombuffer(photo, np.uint8), cv2.IMREAD_COLOR)
    img = img[: keep_h or img.shape[0], : keep_w or img.shape[1]]
    return cv2.imencode(".jpg", img)[1].tobytes(), img.shape[:2]


def card_px(card, size) -> tuple[float, float]:
    """Width and height of a found card, in pixels of the photo."""
    h, w = size
    corners = np.array(card.corners) * [w, h]
    return float(np.linalg.norm(corners[1] - corners[0])), float(np.linalg.norm(corners[3] - corners[0]))


def test_finds_cards_running_off_the_bottom_of_the_photo():
    # deck_photo's second row starts at y=310 and its cards are 210 tall: keep 60% of them.
    photo, size = cut_photo(deck_photo(8), keep_h=310 + 126)
    cards = find_cards(photo)
    assert len(cards) == 8
    for card in cards[4:]:
        assert max(y for _, y in card.corners) > 1  # rebuilt past the photo's edge
        assert card_px(card, size) == pytest.approx((150, 210), abs=8)  # to a full card


def test_finds_cards_running_off_the_side_of_the_photo():
    # The fourth column starts at x=640 and its cards are 150 wide: keep 70% of them.
    photo, size = cut_photo(deck_photo(8), keep_w=640 + 105)
    cards = find_cards(photo)
    assert len(cards) == 8
    for card in (cards[3], cards[7]):
        assert max(x for x, _ in card.corners) > 1
        assert card_px(card, size) == pytest.approx((150, 210), abs=8)


def test_ignores_a_sliver_of_a_card_at_the_edge():
    # Only 20% of the second row is in the photo: too little to be worth a guess.
    photo, _ = cut_photo(deck_photo(8), keep_h=310 + 42)
    assert len(find_cards(photo)) == 4


@pytest.mark.parametrize(
    "offset",
    [(-14, -14), (-30, 0), (14, 14), (30, 0)],
    ids=["corner-wise", "sideways", "corner-wise-reversed", "sideways-reversed"],
)
def test_boxes_the_front_card_of_each_fanned_stack(offset):
    """Fanned stacks (deck builder screenshots, decks laid out by copies) give one card each: the one on top."""
    photo, fronts = stack_photo(offset)
    size = (900, 1200)
    cards = find_cards(photo)
    assert len(cards) == len(fronts)
    for card, (fx, fy) in zip(cards, fronts):
        corners = np.array(card.corners) * [size[1], size[0]]
        assert corners.min(axis=0) == pytest.approx((fx, fy), abs=6)  # not the stack's corner
        assert card_px(card, size) == pytest.approx((150, 210), abs=8)


def test_rectangle_search_finds_cards_whose_outline_is_broken():
    """Dim photos and glare leave outlines open; card-sized rectangles on the edges are still found."""
    gray = np.full((900, 1200), 60, np.uint8)
    cw, ch = 150, 210
    tops = [(80 + c * 220, 80 + r * 300) for r in range(2) for c in range(4)]
    for x, y in tops:
        cv2.rectangle(gray, (x, y), (x + cw, y + ch), 200, -1)
        # Wash out each corner, so no outline closes.
        for cx, cy in [(x, y), (x + cw, y), (x, y + ch), (x + cw, y + ch)]:
            cv2.circle(gray, (cx, cy), 18, 60, -1)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    found = [np.array([[x, y], [x + cw, y], [x + cw, y + ch], [x, y + ch]], np.float32) for x, y in tops[:2]]
    added = sorted(b.min(axis=0).tolist() for b in card_sized_rectangles(gray, found))
    assert len(added) == len(tops) - 2
    assert np.abs(np.array(added) - sorted(tops[2:])).max() <= 6


def test_rectangle_search_skips_a_rectangle_straddling_two_cards():
    gray = np.full((600, 1200), 60, np.uint8)
    cw, ch = 150, 210
    tops = [(100 + c * 160, 100) for c in range(5)]  # cards side by side, 10 px apart
    for x, y in tops:
        cv2.rectangle(gray, (x, y), (x + cw, y + ch), 200, -1)
    found = [np.array([[x, y], [x + cw, y], [x + cw, y + ch], [x, y + ch]], np.float32) for x, y in tops]
    assert card_sized_rectangles(cv2.GaussianBlur(gray, (5, 5), 0), found) == []


def test_no_cards_made_up_on_a_busy_background():
    """On noise or a patterned mat edges are everywhere; the rectangle search mustn't box empty patches."""
    img = cv2.imdecode(np.frombuffer(deck_photo(8), np.uint8), cv2.IMREAD_COLOR)
    table = (img == img[5, 5]).all(axis=2)
    noise = cv2.GaussianBlur((np.random.default_rng(0).random(img.shape[:2]) * 255).astype(np.uint8), (3, 3), 0)
    img[table] = np.stack([noise] * 3, axis=2)[table]
    assert len(find_cards(cv2.imencode(".jpg", img)[1].tobytes())) == 8


def test_tiny_photos_are_not_blown_up_past_their_edges():
    img = cv2.imdecode(np.frombuffer(deck_photo(8), np.uint8), cv2.IMREAD_COLOR)
    tiny = cv2.resize(img, (200, 150), interpolation=cv2.INTER_AREA)
    assert len(find_cards(cv2.imencode(".png", tiny)[1].tobytes())) == 8


def broken_outline_cards(tops, cw=150, ch=210, size=(900, 1200)) -> np.ndarray:
    """Cards whose corners are washed out, so no outline closes, as a blurred grey photo."""
    gray = np.full(size, 60, np.uint8)
    for x, y in tops:
        cv2.rectangle(gray, (x, y), (x + cw, y + ch), 200, -1)
        for cx, cy in [(x, y), (x + cw, y), (x, y + ch), (x + cw, y + ch)]:
            cv2.circle(gray, (cx, cy), 18, 60, -1)
    return cv2.GaussianBlur(gray, (5, 5), 0)


def box(x, y, w, h) -> np.ndarray:
    return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], np.float32)


def test_size_check_replaces_outlines_that_are_not_the_decks_cards():
    """On a busy mat the only outlines that close can be small bits of pattern or art.
    Their size mustn't become the card size the rectangle search looks for."""
    tops = [(80 + c * 220, 80 + r * 300) for r in range(2) for c in range(4)]
    gray = broken_outline_cards(tops)
    junk = [box(1000, 700 + i * 60, 30, 42) for i in range(3)]  # card-shaped, but a fifth of a card
    kept, seeds = check_card_size(gray, junk)
    assert kept == []
    assert len(seeds) >= 3
    assert np.median([b[2][1] - b[0][1] for b in seeds]) == pytest.approx(210, rel=0.12)
    added = sorted(b.min(axis=0).tolist() for b in card_sized_rectangles(gray, kept, seeds))
    assert len(added) == len(tops)
    assert np.abs(np.array(added) - sorted(tops)).max() <= 6


def test_size_check_keeps_outlines_of_the_right_size():
    tops = [(80 + c * 220, 80 + r * 300) for r in range(2) for c in range(4)]
    gray = broken_outline_cards(tops)
    found = [box(x, y, 150, 210) for x, y in tops[:2]]
    kept, seeds = check_card_size(gray, found)
    assert kept is found and seeds == []
