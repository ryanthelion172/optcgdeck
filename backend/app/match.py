"""Identifies a card by comparing its picture with every card's official image.

Each card image is boiled down to a small "fingerprint" of its art: a tiny
colour thumbnail plus the shape of its edges (HOG). Fingerprints for every card
are made once by scripts/build_image_index.py and saved in
backend/.image-index.npz. A crop from a photo gets the same fingerprint, and
the closest card wins if it's clearly closer than the next best.

Both parts are normalised, so lighting and white balance matter little.
Reprints and alternate arts share their art, so they can come out as each
other; ocr.py, which reads the printed number, runs first.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("uvicorn.error")

INDEX_FILE = Path(__file__).resolve().parent.parent / ".image-index.npz"
VERSION = 1  # bump when the fingerprint changes, so old index files are rebuilt

# The art: the top part of the card, inside the frame.
ART = (0.06, 0.94, 0.05, 0.62)  # left, right, top, bottom, as shares of the card
COLOR_SIZE = 12
HOG_SIZE = 64
_local = threading.local()


def _hog() -> cv2.HOGDescriptor:
    """One HOG descriptor per thread, since crops are matched in parallel."""
    if not hasattr(_local, "hog"):
        _local.hog = cv2.HOGDescriptor((HOG_SIZE, HOG_SIZE), (16, 16), (8, 8), (8, 8), 9)
    return _local.hog

# A match is accepted when it's this close, and this much closer than the next card.
MIN_SCORE = 0.6
HIGH = (0.75, 0.10)  # score and lead for "High" confidence
MEDIUM = (0.62, 0.05)
MIN_LEAD = 0.05


def _unit(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.float32).ravel()
    v -= v.mean()
    n = np.linalg.norm(v)
    return v / n if n else v


def fingerprint(img: np.ndarray) -> np.ndarray:
    """A unit-length vector describing a card's art. `img` is a BGR card image, upright."""
    h, w = img.shape[:2]
    left, right, top, bottom = ART
    art = img[int(h * top) : int(h * bottom), int(w * left) : int(w * right)]
    lab = cv2.cvtColor(cv2.resize(art, (COLOR_SIZE, COLOR_SIZE), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2LAB)
    # Each channel on its own scale, so a warm or dim photo still lines up.
    color = np.concatenate([_unit(lab[:, :, c]) for c in range(3)]) / np.sqrt(3)
    gray = cv2.cvtColor(cv2.resize(art, (HOG_SIZE, HOG_SIZE), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    shape = _unit(_hog().compute(gray))
    return np.concatenate([color, shape]) / np.sqrt(2)


# The outline finder sometimes cuts a little inside the card (its inner frame) or
# a little outside (a sleeve or shadow), so the crop is also tried zoomed.
ZOOMS = (1.0, 0.92, 1.08)


def zoom(img: np.ndarray, factor: float) -> np.ndarray:
    """Below 1, keeps the middle of the image; above 1, adds a border. Same size out."""
    if factor == 1.0:
        return img
    h, w = img.shape[:2]
    if factor < 1:
        dy, dx = int(h * (1 - factor) / 2), int(w * (1 - factor) / 2)
        return cv2.resize(img[dy : h - dy, dx : w - dx], (w, h))
    by, bx = int(h * (factor - 1) / 2), int(w * (factor - 1) / 2)
    return cv2.resize(cv2.copyMakeBorder(img, by, by, bx, bx, cv2.BORDER_REPLICATE), (w, h))


@dataclass
class Match:
    card_id: str
    score: float
    confidence: str | None  # None: not sure enough to use
    runners_up: list[tuple[str, float]]
    # The printing whose art matched best: the card id itself for the base art,
    # or an alternate art's id such as "OP01-016_p1".
    printing: str | None = None


class ImageIndex:
    def __init__(self, ids: list[str], vectors: np.ndarray, printings: list[str] | None = None) -> None:
        self.ids = ids  # base card id for each row (alternate arts map to their card)
        self.vectors = vectors.astype(np.float32)
        # The printing each row's image is of. Index files saved before this was
        # kept don't have it, so every row counts as its card's base art.
        self.printings = printings if printings is not None and len(printings) == len(ids) else list(ids)

    def __len__(self) -> int:
        return len(self.ids)

    def best(self, img: np.ndarray, only: set[str] | None = None) -> Match | None:
        """The closest card to the crop `img`, trying it both ways up.

        With `only`, just those card ids are compared (e.g. every printing of a
        name read off the card), so the lead needed is over those cards alone.
        """
        rows = np.arange(len(self.ids)) if only is None else np.array(
            [i for i, card_id in enumerate(self.ids) if card_id in only], dtype=int
        )
        if not len(rows):
            return None
        views = [fingerprint(v) for z in ZOOMS for v in (zoom(img, z), zoom(cv2.rotate(img, cv2.ROTATE_180), z))]
        scores = np.max(self.vectors[rows] @ np.stack(views).T, axis=1)
        # Best score per card id (a card's alternate arts all count as that card).
        per_card: dict[str, float] = {}
        best_printing: dict[str, str] = {}
        for i in np.argsort(-scores)[:50]:
            card_id = self.ids[rows[i]]
            if card_id not in per_card:
                per_card[card_id] = float(scores[i])
                best_printing[card_id] = self.printings[rows[i]]
        ranked = sorted(per_card.items(), key=lambda kv: -kv[1])
        card_id, score = ranked[0]
        lead = score - (ranked[1][1] if len(ranked) > 1 else 0.0)
        if score >= HIGH[0] and lead >= HIGH[1]:
            confidence = "High"
        elif score >= MEDIUM[0] and lead >= MEDIUM[1]:
            confidence = "Medium"
        elif score >= MIN_SCORE and lead >= MIN_LEAD:
            confidence = "Low"
        else:
            confidence = None
        return Match(card_id, score, confidence, [(c, round(s, 3)) for c, s in ranked[1:4]], best_printing[card_id])

    def save(self, path: Path = INDEX_FILE) -> None:
        tmp = path.with_name(path.stem + ".tmp.npz")
        np.savez_compressed(
            tmp, ids=np.array(self.ids), printings=np.array(self.printings), vectors=self.vectors, version=VERSION
        )
        tmp.replace(path)


_lock = threading.Lock()
_loaded: tuple[float, ImageIndex | None] | None = None


def load_index(path: Path = INDEX_FILE) -> ImageIndex | None:
    """The saved index, re-read whenever the file changes. None if it hasn't been built."""
    global _loaded
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None
    with _lock:
        if _loaded is None or _loaded[0] != mtime:
            index = None
            try:
                with np.load(path) as data:
                    if int(data["version"]) == VERSION:
                        printings = [str(i) for i in data["printings"]] if "printings" in data.files else None
                        index = ImageIndex([str(i) for i in data["ids"]], data["vectors"], printings)
                    else:
                        log.warning("%s is out of date; run scripts/build_image_index.py again.", path.name)
            except Exception as exc:  # a damaged file shouldn't break scanning
                log.warning("Couldn't read %s (%s); run scripts/build_image_index.py again.", path.name, exc)
            _loaded = (mtime, index)
        return _loaded[1]
