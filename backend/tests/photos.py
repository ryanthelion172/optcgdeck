"""Builds fake deck photos for the detection tests."""

import cv2
import numpy as np


def deck_photo(n: int = 6, size=(1200, 900), rotate_last: bool = False, background=(40, 30, 25)) -> bytes:
    """`n` card-shaped rectangles laid out in a grid on a plain background, as a JPEG."""
    h, w = size
    img = np.full((h, w, 3), background, np.uint8)
    cw, ch = 150, 210  # 63 x 88 mm card shape
    cols = 4
    for i in range(n):
        x, y = 40 + (i % cols) * (cw + 50), 40 + (i // cols) * (ch + 60)
        card = np.full((ch, cw, 3), (200, 210, 220), np.uint8)
        cv2.rectangle(card, (12, 12), (cw - 12, ch // 2), (60 + 30 * i % 200, 90, 160), -1)  # "art"
        cv2.putText(card, f"C{i}", (20, ch - 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (20, 20, 20), 2)
        if rotate_last and i == n - 1:
            card = cv2.rotate(card, cv2.ROTATE_90_CLOCKWISE)
        ph, pw = card.shape[:2]
        img[y : y + ph, x : x + pw] = card
    return cv2.imencode(".jpg", img)[1].tobytes()


def blank_photo() -> bytes:
    return cv2.imencode(".png", np.full((400, 300, 3), 128, np.uint8))[1].tobytes()
