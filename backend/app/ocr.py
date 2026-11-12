"""Reads the card number (e.g. "OP01-016") printed in a card's bottom-right corner.

Works on a straightened crop from detect.py. Only the bottom strip is read, so
it's quick. The text is small, so it reads well on close or sharp photos and
often not at all on a photo of a whole deck taken from far away; the image
match in match.py covers those.

The OCR engine (RapidOCR) runs locally: no API calls.
"""

from __future__ import annotations

import re
import threading

import cv2
import numpy as np

# The number sits along the bottom edge. A strip this tall leaves room for
# crops that are a little off (a bit of table, or only the inner frame).
STRIP = (0.86, 1.0)  # top and bottom of the strip, as a share of the card height
STRIP_LEFT = 0.4  # the number is on the right, so the left of the strip is skipped
UPSCALE = 2  # the text is tiny; OCR reads it better enlarged

# OCR often mixes up letters and digits that look alike.
AS_DIGIT = str.maketrans({"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "|": "1", "S": "5", "B": "8", "Z": "2", "G": "6"})
PREFIX_FIX = {"0P": "OP", "QP": "OP", "DP": "OP", "5T": "ST", "E8": "EB", "PR8": "PRB"}
NUMBER = re.compile(
    r"(OP|0P|QP|DP|ST|5T|EB|E8|PRB|PR8|P)\s*([0-9ODQILSBZG]{2})?\s*[-–—_.~]?\s*([0-9ODQILSBZG|]{3})(?![0-9])"
)

_engine = None
# One engine, used by one crop at a time: it already uses every CPU core, and
# running several at once only made each one slower.
_lock = threading.Lock()


def _run(img: np.ndarray):
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
        return _engine(img)


def candidates(text: str) -> list[str]:
    """Card numbers that could be in `text`, best guess first."""
    text = text.upper().replace(" ", "")
    found = []
    for m in NUMBER.finditer(text):
        prefix, set_no, number = m.groups()
        prefix = PREFIX_FIX.get(prefix, prefix)
        number = number.translate(AS_DIGIT)
        if set_no:
            found.append(f"{prefix}{set_no.translate(AS_DIGIT)}-{number}")
        elif prefix == "P":
            found.append(f"P-{number}")  # promos: P-001
    return found


def read_strip(img: np.ndarray) -> str:
    """All the text OCR finds in the card's bottom strip."""
    h = img.shape[0]
    w = img.shape[1]
    strip = img[int(h * STRIP[0]) : int(h * STRIP[1]), int(w * STRIP_LEFT) :]
    strip = cv2.resize(strip, None, fx=UPSCALE, fy=UPSCALE, interpolation=cv2.INTER_CUBIC)
    result, _ = _run(strip)
    return " ".join(text for _, text, _ in (result or []))


def read_number(img: np.ndarray, store, upside_down: bool = False) -> tuple[str | None, str]:
    """Returns (card id, text read). The id is None unless a real card number was read.

    With `upside_down`, reads the card turned over (its top-left corner).
    """
    text = read_strip(cv2.rotate(img, cv2.ROTATE_180) if upside_down else img)
    for card_id in candidates(text):
        if store.get(card_id):
            return card_id, text
    return None, text
