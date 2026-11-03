import cv2
import numpy as np
import pytest

from app.detect import CROP_SIZE, BadImage, find_cards

from .photos import blank_photo, deck_photo, single_card_photo


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
