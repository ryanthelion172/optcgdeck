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


def single_card_photo(fill: float = 0.85, size=(1600, 1200)) -> bytes:
    """One card, centred, its height `fill` times the photo's; above 1 it runs off the edges."""
    h, w = size
    ch = int(h * fill)
    cw = int(ch * 63 / 88)
    card = np.full((ch, cw, 3), (30, 30, 200), np.uint8)  # red border
    cv2.rectangle(card, (int(cw * 0.05), int(ch * 0.04)), (int(cw * 0.95), int(ch * 0.7)), (120, 160, 90), -1)  # art
    cv2.rectangle(card, (int(cw * 0.08), int(ch * 0.62)), (int(cw * 0.92), int(ch * 0.95)), (230, 230, 230), -1)
    img = np.full((h, w, 3), (60, 50, 40), np.uint8)
    y0, x0 = (h - ch) // 2, (w - cw) // 2
    ys, xs = max(0, y0), max(0, x0)
    part = card[ys - y0 : ys - y0 + min(h - ys, ch), xs - x0 : xs - x0 + min(w - xs, cw)]
    img[ys : ys + part.shape[0], xs : xs + part.shape[1]] = part
    return cv2.imencode(".jpg", img)[1].tobytes()


def stack_photo(offset=(-14, -14), stacks: int = 3, per_stack: int = 4, size=(900, 1200)) -> tuple[bytes, list[tuple[int, int]]]:
    """Stacks of cards fanned out like a deck builder shows them, each card laid on the one before.

    `offset` is how far each card behind sits from the one in front of it. Returns
    the JPEG and each front card's top-left corner.
    """
    h, w = size
    img = np.full((h, w, 3), (40, 60, 120), np.uint8)
    cw, ch = 150, 210
    fronts = []
    for s in range(stacks):
        fx, fy = 120 + s * 340, 200
        for k in range(per_stack - 1, -1, -1):  # back card first, front card last
            x, y = fx + k * offset[0], fy + k * offset[1]
            card = np.full((ch, cw, 3), (200, 210, 220), np.uint8)
            cv2.rectangle(card, (0, 0), (cw - 1, ch - 1), (30, 30, 30), 3)  # sleeve edge
            cv2.rectangle(card, (14, 14), (cw - 14, ch // 2), (60 + 40 * s, 90, 160), -1)  # "art"
            img[y : y + ch, x : x + cw] = card
        fronts.append((fx, fy))
    return cv2.imencode(".jpg", img)[1].tobytes(), fronts
