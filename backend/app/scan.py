"""Turns a photo of cards into card ids.

OpenCV finds each card in the photo (see detect.py) and cuts it out. Each card
is then identified, trying in order:

1. "set code": reading the card number printed in its bottom-right corner (ocr.py).
2. "image match": comparing its art with every card's image (match.py). Needs
   the index from scripts/build_image_index.py; skipped until that's been run.
   When that match is weak or missing, "name + image match": reading the name
   printed at the bottom (ocr.py), then comparing the art with only the cards
   that have that name.

Each result says which step found it. Cards none of them could place come back
with their crop and the closest card, for the user to confirm or search for.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from .detect import CROP_SIZE, decode, find_cards
from .match import ImageIndex, Match, load_index

log = logging.getLogger("uvicorn.error")

PARALLEL_CALLS = 8
CONFIDENCE_ORDER = ["Low", "Medium", "High"]


def detection(card_id: str, confidence: str, via: str, printing: str | None = None) -> dict:
    """One identified card. `printing` is the art the image match saw (an alternate
    art's id such as "OP01-016_p1"), when it differs from the base art."""
    det = {"id": card_id, "confidence": confidence, "via": via}
    if printing and printing != card_id:
        det["printing"] = printing
    return det


def count_cards(found: list[dict]) -> list[dict]:
    """Groups detections into one entry per card, with how many copies were found.

    Each card keeps the lowest confidence seen for it, every step that found it,
    and the first alternate art the image match saw for it, if any.
    """
    counts: dict[str, dict] = {}
    for det in found:
        entry = counts.setdefault(det["id"], {"id": det["id"], "count": 0, "confidence": det["confidence"], "via": []})
        entry["count"] += 1
        if det["via"] not in entry["via"]:
            entry["via"].append(det["via"])
        if det.get("printing") and "printing" not in entry:
            entry["printing"] = det["printing"]
        if CONFIDENCE_ORDER.index(det["confidence"]) < CONFIDENCE_ORDER.index(entry["confidence"]):
            entry["confidence"] = det["confidence"]
    return list(counts.values())


def data_url(jpeg: bytes) -> str:
    """A JPEG as a data: URL, so the app can show it without another request."""
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


def recognise_card(img: np.ndarray, store, index: ImageIndex | None) -> tuple[dict | None, dict]:
    """Identifies one card image: its printed number, then its art, then its name.

    The number is read the right way up first. If the art match is weak or
    missing, the card's name is read and the art is compared with only the cards
    of that name. Only if none of that works is the number read upside down,
    since reading is the slow part.
    Returns (detection or None, what each step saw, for debugging).
    """
    seen: dict = {}

    def read(upside_down: bool) -> dict | None:
        try:
            from .ocr import read_number

            card_id, text = read_number(img, store, upside_down)
        except ImportError:
            seen["setCodeRead"] = "OCR not installed (pip install -r requirements.txt)"
            return None
        except Exception as exc:  # never let the reader break a scan
            log.warning("Reading the card number failed: %s", exc)
            seen["setCodeRead"] = f"failed: {exc}"
            return None
        seen["setCodeRead"] = " / ".join(t for t in (seen.get("setCodeRead"), text) if t)
        return detection(card_id, "High", "set code") if card_id else None

    if found := read(upside_down=False):
        return found, seen
    m = None
    if index is None:
        seen["imageMatch"] = "image match off: run scripts/build_image_index.py"
    elif m := index.best(img):
        seen["imageMatch"] = {
            "card": m.card_id, "printing": m.printing, "score": round(m.score, 3), "confidence": m.confidence,
            "runnersUp": m.runners_up,
        }
        if m.confidence in ("High", "Medium"):
            return detection(m.card_id, m.confidence, "image match", m.printing), seen
    if index is not None and (found := by_name(img, store, index, m, seen)):
        return found, seen
    if m is not None and m.confidence:  # a weak art match, and the name didn't help
        return detection(m.card_id, m.confidence, "image match", m.printing), seen
    if "not installed" not in seen.get("setCodeRead", "") and (found := read(upside_down=True)):
        return found, seen
    return None, seen


def by_name(img: np.ndarray, store, index: ImageIndex, art: Match | None, seen: dict) -> dict | None:
    """When the art match is weak or missing: reads the card's name, then matches the
    art against only the cards with that name. None if no name could be read.
    """
    try:
        from .ocr import read_name

        ids, text = read_name(img, store)
        if not ids:
            ids, text_turned = read_name(img, store, upside_down=True)
            text = " / ".join(t for t in (text, text_turned) if t)
    except ImportError:
        return None
    except Exception as exc:  # never let the reader break a scan
        log.warning("Reading the card name failed: %s", exc)
        seen["nameRead"] = f"failed: {exc}"
        return None
    seen["nameRead"] = text
    if not ids:
        return None
    if art is not None and art.card_id in ids:
        # The weak art match agrees with the name: trust it a bit more.
        return detection(art.card_id, "Medium", "name + image match", art.printing)
    m = index.best(img, only=set(ids))
    if m is None:  # none of the cards with that name are in the image index
        return detection(ids[0], "Low", "name") if len(ids) == 1 else None
    seen["nameMatch"] = {"card": m.card_id, "printing": m.printing, "score": round(m.score, 3), "runnersUp": m.runners_up}
    # One card with that name: the name settles it. Several (reprints, other
    # versions): the art picks one, so it's worth a look.
    confidence = "Medium" if len(set(ids)) == 1 or (m.confidence in ("High", "Medium")) else "Low"
    return detection(m.card_id, confidence, "name + image match", m.printing)


Recognise = Callable[[np.ndarray, object, ImageIndex | None], tuple[dict | None, dict]]


def describe(seen: dict) -> str:
    """A short note on why a card wasn't placed, shown under its picture."""
    parts = []
    text = seen.get("setCodeRead")
    parts.append(f'Read "{text}"' if text else "No number read")
    m = seen.get("imageMatch")
    if isinstance(m, dict):
        parts.append(f"closest art {m['card']} ({m['score']:.2f})")
    elif m:
        parts.append(m)  # e.g. the image index hasn't been built
    if "nameRead" in seen:
        parts.append(f'name read "{seen["nameRead"]}"' if seen["nameRead"] else "no name read")
    return "; ".join(parts)


def closest_match(seen: dict) -> dict | None:
    """The match the local search thinks is nearest, offered to the user to confirm.

    The match among cards with the name read wins over the plain art match: it
    agrees with the text on the card as well as the picture.
    """
    for key in ("nameMatch", "imageMatch"):
        m = seen.get(key)
        if isinstance(m, dict) and m.get("card"):
            return m
    return None


def closest(seen: dict) -> str | None:
    """The card id of the nearest match (see closest_match)."""
    m = closest_match(seen)
    return m["card"] if m else None


def unmatched_entry(label: str, seen: dict, jpeg: bytes | None) -> dict:
    """One card that wasn't placed: its crop, why, and the closest card if any."""
    entry = {"label": label, "detail": describe(seen)}
    if jpeg:
        entry["image"] = data_url(jpeg)
    if guess := closest_match(seen):
        entry["closest"] = guess["card"]
        # The art it matched, so the app shows that alternate art and not the base one.
        if guess.get("printing") and guess["printing"] != guess["card"]:
            entry["closestPrinting"] = guess["printing"]
    return entry


def shrink(img: np.ndarray, longest: int = CROP_SIZE[1]) -> np.ndarray:
    """Scales a photo down so its longest side is `longest` pixels (never up)."""
    h, w = img.shape[:2]
    scale = longest / max(h, w)
    if scale >= 1:
        return img
    return cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)


def scan_single(image: bytes, store, recognise: Recognise | None = None) -> dict:
    """Identifies the one card in a photo, close up or with some background around it.

    The straightened crop is tried first, then the whole photo (a close-up can
    hide the card's edges and leave only an inner frame to crop).
    """
    recognise = recognise or recognise_card
    crops = find_cards(image, single=True)
    index = load_index()
    crop_jpeg = crops[0].jpeg if crops else None
    # Decoded only when needed. The whole photo is shrunk to about a crop's size:
    # a phone photo is 10x bigger, which only makes reading and matching slow.
    views = ([lambda: decode(crop_jpeg)] if crop_jpeg else []) + [lambda: shrink(decode(image))]
    seen_all, pick = [], None
    for view in views:
        pick, seen = recognise(view(), store, index)
        seen_all.append(seen)
        if pick:
            break
    return {
        "detected": 1,
        "cards": count_cards([pick] if pick else []),
        "unmatched": [] if pick else [unmatched_entry("The card in the photo (not recognised)", seen_all[0], crop_jpeg)],
        "cardsFound": len(crops),
        "raw": {"local": seen_all, "cards": [{"card": 1, "corners": c.corners} for c in crops]},
    }


def scan(image: bytes, store, single: bool = False, recognise: Recognise | None = None) -> dict:
    """Finds the cards in a photo and identifies each one.

    When the outline finder found no cards, or found one it couldn't identify,
    the photo is most likely a close-up of one card, so it's read as one (see
    scan_single). With `single`, the photo is always read that way.
    """
    if single:
        return scan_single(image, store, recognise)
    recognise = recognise or recognise_card
    crops = find_cards(image)
    index = load_index()
    with ThreadPoolExecutor(PARALLEL_CALLS) as pool:
        local = list(pool.map(lambda c: recognise(decode(c.jpeg), store, index), crops))

    if len(crops) <= 1 and not any(found for found, _ in local):
        whole = scan_single(image, store, recognise)
        if whole["cards"] or not crops:
            return whole

    unmatched = [
        unmatched_entry(f"Card {i + 1} in the photo (not recognised)", seen, crops[i].jpeg)
        for i, (found, seen) in enumerate(local)
        if not found
    ]
    return {
        "detected": len(crops),
        "cards": count_cards([found for found, _ in local if found]),
        "unmatched": unmatched,
        "cardsFound": len(crops),
        "raw": {
            "cards": [
                {"card": i + 1, "corners": crops[i].corners, **seen, "via": found["via"] if found else None}
                for i, (found, seen) in enumerate(local)
            ]
        },
    }
