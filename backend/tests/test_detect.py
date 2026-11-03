import cv2
import numpy as np
import pytest

from app.detect import CROP_SIZE, BadImage, find_cards

from .photos import blank_photo, deck_photo


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
