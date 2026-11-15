"""Reads the card number (e.g. "OP01-016") printed in a card's bottom-right corner.

Works on a straightened crop from detect.py. Only the bottom strip is read, so
it's quick. The text is small, so it reads well on close or sharp photos and
often not at all on a photo of a whole deck taken from far away; the image
match in match.py covers those.

The OCR engine (RapidOCR) runs locally: no API calls.
"""

from __future__ import annotations

import difflib
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


# The card's name is printed large, centred near the bottom, above its types
# (Leaders, Characters and Events alike). The strip also takes in the types line
# and the end of the effect text; those rarely look like a card name.
NAME_STRIP = (0.70, 1.0)
NAME_SIDES = (0.05, 0.95)
MIN_NAME_SCORE = 0.8  # how alike the text read and a card name must be (0 to 1)
# Reads this short (e.g. "A/PS" from a smudge) are alike too many short names
# ("Apis", "Yu", "Ohm") by chance, so they only count when they match exactly.
EXACT_BELOW = 5
_names_for: tuple[object, dict[str, list[str]], set[str]] | None = None  # (store, names, types)


def _key(text: str) -> str:
    """A name boiled down for comparing: lower case letters and digits only."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _load_names(store) -> tuple[dict[str, list[str]], set[str]]:
    global _names_for
    if _names_for is None or _names_for[0] is not store:
        by_name: dict[str, list[str]] = {}
        types: set[str] = set()
        for card in store.cards:
            if key := _key(card.get("name") or ""):
                by_name.setdefault(key, []).append(card["id"])
            types.update(_key(t) for t in card.get("types") or [])
        _names_for = (store, by_name, types)
    return _names_for[1], _names_for[2]


def names(store) -> dict[str, list[str]]:
    """Each card name (as a key, see _key) and the ids of the cards with that name."""
    return _load_names(store)[0]


def _closest(key: str, choices, floor: float) -> tuple[str, float] | None:
    """The choice most like `key` (difflib ratio), if any reaches `floor`."""
    best, best_score = None, floor
    matcher = difflib.SequenceMatcher(autojunk=False)
    matcher.set_seq2(key)
    for choice in choices:
        # Cheap checks first: names much longer or shorter can't be close.
        if 2 * min(len(choice), len(key)) / (len(choice) + len(key)) < best_score:
            continue
        matcher.set_seq1(choice)
        if matcher.real_quick_ratio() >= best_score and matcher.quick_ratio() >= best_score:
            score = matcher.ratio()
            if score >= best_score:
                best, best_score = choice, score
    return (best, best_score) if best else None


def match_name(text: str, store) -> tuple[str, float, bool] | None:
    """The card name (key) most like `text`, how alike they are (0 to 1), and whether
    the text could just as well be a types line. None if no name is close.

    About 20 card names are also types ("Impel Down", "Baroque Works", "Rocks
    Pirates"), so a types line can look exactly like a name; read_name decides
    those by text size. Text more like a type than any name is skipped.
    """
    key = _key(text)
    if len(key) < 2:
        return None
    by_name, types = _load_names(store)
    if key in by_name:
        found = (key, 1.0)
    elif len(key) < EXACT_BELOW:
        return None
    else:
        found = _closest(key, by_name, MIN_NAME_SCORE)
    if not found:
        return None
    type_score = 1.0 if key in types else (_closest(key, types, found[1]) or ("", 0.0))[1]
    if type_score > found[1]:
        return None
    return found[0], found[1], type_score >= found[1]


# The name is printed about twice the size of the types line and effect text. A
# line that could be either a name or a types line counts as the name only if
# it's clearly bigger than the other text around it.
NAME_SIZE = 1.4


def read_name(img: np.ndarray, store, upside_down: bool = False) -> tuple[list[str], str]:
    """Reads the card's name. Returns (ids of every card with that name, text read).

    The ids list is empty when no line of text looks enough like a card name.
    When several lines do, the tallest text wins, since the name is printed
    larger than anything else down there. A line that is also a type (e.g.
    "Impel Down") is only taken when it's printed name-sized, so the types line
    under an unreadable name isn't mistaken for it.
    """
    if upside_down:
        img = cv2.rotate(img, cv2.ROTATE_180)
    h, w = img.shape[:2]
    strip = img[int(h * NAME_STRIP[0]) : int(h * NAME_STRIP[1]), int(w * NAME_SIDES[0]) : int(w * NAME_SIDES[1])]
    result, _ = _run(strip)
    lines = [(text, max(p[1] for p in box) - min(p[1] for p in box)) for box, text, _conf in result or []]
    best = None  # (text height, score, name key)
    for i, (text, height) in enumerate(lines):
        found = match_name(text, store)
        if not found:
            continue
        key, score, could_be_type = found
        if could_be_type:
            others = sorted(hgt for j, (_, hgt) in enumerate(lines) if j != i)
            if not others or height < NAME_SIZE * others[len(others) // 2]:
                continue
        if best is None or (height, score) > best[:2]:
            best = (height, score, key)
    return (names(store)[best[2]] if best else []), " ".join(text for text, _ in lines)
