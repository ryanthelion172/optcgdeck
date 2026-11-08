"""Turns a photo of cards into card ids.

OpenCV finds each card in the photo (see detect.py) and cuts it out. Each card
is then identified, trying in order:

1. "set code": reading the card number printed in its bottom-right corner (ocr.py).
2. "image match": comparing its art with every card's image (match.py). Needs
   the index from scripts/build_image_index.py; skipped until that's been run.
3. "CardSight": the CardSight AI API, only for cards the first two couldn't
   place. The API key is read from CARDSIGHTAI_API_KEY (put it in backend/.env).

Steps 1 and 2 run locally. In a deck scan, the whole photo is also sent to
CardSight once if any card is left over, to catch cards the outline finder
missed. Each result says which step found it.
"""

from __future__ import annotations

import base64
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import numpy as np

from .detect import decode, find_cards
from .match import ImageIndex, load_index

log = logging.getLogger("uvicorn.error")

SEGMENT = "onepiece"
PARALLEL_CALLS = 8
CONFIDENCE = {"High": 3, "Medium": 2, "Low": 1}

CARD_ID = re.compile(r"\b([A-Z]{1,4}\d{0,2})-?(\d{3})\b", re.IGNORECASE)
SET_CODE = re.compile(r"\b(OP|ST|EB|PRB)-?(\d{2})\b", re.IGNORECASE)
DIGITS = re.compile(r"^\D*(\d{1,3})\D*$")


class ScanError(Exception):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def identify(image: bytes, filename: str, mime_type: str) -> list[dict]:
    """Sends the photo to CardSight and returns its detections as plain dicts."""
    try:
        from cardsightai import CardSightAI
        from cardsightai.exceptions import AuthenticationError
        from cardsightai.generated.card_sight_ai_api_client.api.card_identification import (
            identify_card_by_segment,
        )
        from cardsightai.generated.card_sight_ai_api_client.models.file_upload_input import (
            FileUploadInput,
        )
        from cardsightai.generated.card_sight_ai_api_client.types import File
    except ImportError as exc:
        raise ScanError("The cardsightai package isn't installed on the backend.", 500) from exc

    try:
        client = CardSightAI()  # reads CARDSIGHTAI_API_KEY from the environment
    except AuthenticationError as exc:
        raise ScanError("Set CARDSIGHTAI_API_KEY in backend/.env to use photo scanning.", 503) from exc

    try:
        # The SDK's identify helper leaves out the file name and type, which the
        # API rejects, so build the upload ourselves (same as scan_one.py).
        body = FileUploadInput(
            image=File(payload=BytesIO(image), file_name=filename, mime_type=mime_type)
        )
        result = identify_card_by_segment.sync(
            SEGMENT, client=client._async_client._client, body=body
        )
    except Exception as exc:  # network errors, unexpected statuses
        raise ScanError(f"Couldn't reach the scanning service: {exc}") from exc
    finally:
        client.close()

    if result is None:
        raise ScanError("The scanning service sent an unexpected response.")
    data = result.to_dict()
    if "error" in data:
        raise ScanError(f"Scanning service error: {data['error']}")
    return data.get("detections") or []


def label(card: dict) -> str:
    parts = [card.get(k) for k in ("name", "number", "releaseName", "setName")]
    return " · ".join(p for p in parts if p) or "Unknown card"


def match_card(card: dict, store) -> str | None:
    """Finds our card id for one CardSight card, or None if unsure."""
    if card.get("id") and store.get(card["id"]):  # found locally: already our id
        return store.get(card["id"])["id"]
    number = (card.get("number") or "").strip()
    name = (card.get("name") or "").strip().lower()
    set_text = " ".join(filter(None, [card.get("releaseName"), card.get("setName")]))

    # 1. The number is a full card number, e.g. "OP01-016".
    if m := CARD_ID.search(number):
        card_id = f"{m.group(1).upper()}-{m.group(2)}"
        if store.get(card_id):
            return card_id

    # 2. The number is just digits and the set name holds the set code, e.g. "016" + "OP-01".
    digits = DIGITS.match(number)
    set_code = SET_CODE.search(set_text)
    if digits and set_code:
        card_id = f"{set_code.group(1).upper()}{set_code.group(2)}-{int(digits.group(1)):03d}"
        if store.get(card_id):
            return card_id

    # 3. Fall back to the name, if it's unique (or the number picks one).
    if name:
        same_name = [c for c in store.cards if c["name"].lower() == name]
        if digits:
            same_name = [c for c in same_name if c["id"].endswith(f"-{int(digits.group(1)):03d}")] or same_name
        if len(same_name) == 1:
            return same_name[0]["id"]
    return None


def data_url(jpeg: bytes) -> str:
    """A JPEG as a data: URL, so the app can show it without another request."""
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


def build_result(detections: list[dict], store, images: list[bytes | None] | None = None) -> dict:
    """Groups detections into card counts plus a list of cards we couldn't match.

    `images`, if given, holds the crop each detection came from (same order), and
    unmatched cards carry their crop so the app can show what was found.
    """
    counts: dict[str, dict] = {}
    unmatched: list[dict] = []
    order = ["Low", "Medium", "High"]
    for i, det in enumerate(detections):
        card = det.get("card") or {}
        confidence = det.get("confidence") or "Low"
        card_id = match_card(card, store)
        if card_id is None:
            entry = {"label": label(card), "confidence": confidence}
            if images and images[i]:
                entry["image"] = data_url(images[i])
            unmatched.append(entry)
            continue
        entry = counts.setdefault(card_id, {"id": card_id, "count": 0, "confidence": confidence, "via": []})
        entry["count"] += 1
        via = det.get("via", "CardSight")
        if via not in entry["via"]:
            entry["via"].append(via)
        # Keep the lowest confidence seen for this card.
        if order.index(confidence) < order.index(entry["confidence"]):
            entry["confidence"] = confidence
    return {"detected": len(detections), "cards": list(counts.values()), "unmatched": unmatched}


Identify = Callable[[bytes, str, str], list[dict]]


def best(detections: list[dict]) -> dict | None:
    return max(detections, key=lambda d: CONFIDENCE.get(d.get("confidence"), 0), default=None)


def local_detection(card_id: str, confidence: str, via: str) -> dict:
    return {"card": {"id": card_id, "number": card_id}, "confidence": confidence, "via": via}


def recognise_card(img: np.ndarray, store, index: ImageIndex | None) -> tuple[dict | None, dict]:
    """Identifies one card image without CardSight: its printed number, then its art.

    The number is read the right way up first. Only if the art doesn't match
    either is it read upside down, since reading is the slow part.
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
        return local_detection(card_id, "High", "set code") if card_id else None

    if found := read(upside_down=False):
        return found, seen
    if index is None:
        seen["imageMatch"] = "no image index (run scripts/build_image_index.py)"
    elif m := index.best(img):
        seen["imageMatch"] = {
            "card": m.card_id, "score": round(m.score, 3), "confidence": m.confidence, "runnersUp": m.runners_up
        }
        if m.confidence:
            return local_detection(m.card_id, m.confidence, "image match"), seen
    if "not installed" not in seen.get("setCodeRead", "") and (found := read(upside_down=True)):
        return found, seen
    return None, seen


Recognise = Callable[[np.ndarray, object, ImageIndex | None], tuple[dict | None, dict]]


def describe(seen: dict) -> str:
    """A short note on why a card wasn't placed, shown under its picture."""
    parts = []
    text = seen.get("setCodeRead")
    parts.append(f'Read "{text}"' if text else "No number read")
    m = seen.get("imageMatch")
    if isinstance(m, dict):
        parts.append(f"closest art {m['card']} ({m['score']:.2f})")
    return "; ".join(parts)


def call_all(jobs: list[tuple[bytes, str, str]], identify: Identify) -> list[tuple[list[dict], ScanError | None]]:
    """Sends each image to CardSight, in parallel. Errors are returned, not raised."""

    def one(job):
        try:
            return identify(*job), None
        except ScanError as exc:
            return [], exc

    if not jobs:
        return []
    with ThreadPoolExecutor(min(PARALLEL_CALLS, len(jobs))) as pool:
        return list(pool.map(one, jobs))


def check_errors(answers, found_any: bool) -> str | None:
    """Raises a CardSight error when nothing could be identified without it; otherwise returns it as a note."""
    errors = [err for _, err in answers if err]
    if not errors:
        return None
    if not found_any and (len(errors) == len(answers) or any(e.status == 503 for e in errors)):
        raise errors[0]  # e.g. no API key, or the service is down
    return f"CardSight: {errors[0]}"


def scan_single(
    image: bytes, filename: str, mime_type: str, store, identify: Identify = identify, recognise: Recognise | None = None
) -> dict:
    """Identifies the one card in a photo, close up or with some background around it.

    The straightened crop is tried first, then the whole photo (a close-up can
    hide the card's edges and leave only an inner frame to crop). CardSight is
    only asked if neither could be placed locally.
    """
    recognise = recognise or recognise_card
    crops = find_cards(image, single=True)
    index = load_index()
    crop_jpeg = crops[0].jpeg if crops else None
    views = ([decode(crop_jpeg)] if crop_jpeg else []) + [decode(image)]
    seen_all, pick, pick_image = [], None, None
    for i, view in enumerate(views):
        found, seen = recognise(view, store, index)
        seen_all.append(seen)
        if found:
            pick, pick_image = found, (crop_jpeg if i == 0 and crop_jpeg else None)
            break

    raw: dict = {"local": seen_all}
    note = None
    if pick is None:
        jobs = [(image, filename, mime_type)] + ([(crop_jpeg, "card-1.jpg", "image/jpeg")] if crop_jpeg else [])
        answers = call_all(jobs, identify)
        note = check_errors(answers, found_any=False)
        (whole, whole_error), *crop_answer = answers
        crop_found, crop_error = crop_answer[0] if crop_answer else ([], None)
        crop_pick, whole_pick = best(crop_found), best(whole)
        # Prefer the crop on a tie: it's the card alone, straightened.
        pick = best([d for d in (crop_pick, whole_pick) if d])
        pick_image = crop_jpeg if pick is not None and pick is crop_pick else None
        raw["cardsight"] = {
            "crop": {"detections": crop_found, "error": str(crop_error) if crop_error else None} if crop_jpeg else None,
            "wholePhoto": {"detections": whole, "error": str(whole_error) if whole_error else None},
        }

    result = build_result([pick] if pick else [], store, [pick_image])
    if not pick:
        entry = {"label": "The card in the photo (not recognised)", "confidence": "Low", "detail": describe(seen_all[0])}
        if crop_jpeg:
            entry["image"] = data_url(crop_jpeg)
        result["unmatched"] = [entry]
    result["detected"] = 1
    result["cardsFound"] = len(crops)
    if note:
        result["note"] = note
    raw["cards"] = [{"card": 1, "corners": c.corners} for c in crops]
    result["raw"] = raw
    return result


def scan(
    image: bytes,
    filename: str,
    mime_type: str,
    store,
    identify: Identify = identify,
    single: bool = False,
    recognise: Recognise | None = None,
) -> dict:
    """Finds the cards in a photo and identifies each one. Returns build_result plus debug info.

    Each card found is identified on its own: locally first, then with CardSight
    for the ones left over. When any are left over (or no cards were found), the
    whole photo also goes to CardSight once, and any card it recognises that the
    crops missed is added, which helps with cards the outline finder can't
    separate (stacks, cluttered photos).

    With `single`, the photo is of one card (see scan_single).
    """
    if single:
        return scan_single(image, filename, mime_type, store, identify, recognise)
    recognise = recognise or recognise_card
    crops = find_cards(image)
    index = load_index()

    with ThreadPoolExecutor(PARALLEL_CALLS) as pool:
        local = list(pool.map(lambda c: recognise(decode(c.jpeg), store, index), crops))

    left = [i for i, (found, _) in enumerate(local) if found is None]
    jobs = [(image, filename, mime_type)] if left or not crops else []
    jobs += [(crops[i].jpeg, f"card-{i + 1}.jpg", "image/jpeg") for i in left]
    answers = call_all(jobs, identify)
    whole, whole_error = answers[0] if jobs else ([], None)
    cardsight = dict(zip(left, answers[1:]))
    found_locally = any(found for found, _ in local)
    note = check_errors(answers, found_locally)

    detections, images, unreadable = [], [], []
    for i, (found, seen) in enumerate(local):
        if found is None and cardsight[i][0]:
            # Each crop holds one card; keep CardSight's most confident answer.
            found = best(cardsight[i][0])
        if found:
            detections.append(found)
            images.append(crops[i].jpeg)
        else:
            unreadable.append({
                "label": f"Card {i + 1} in the photo (not recognised)",
                "confidence": "Low",
                "image": data_url(crops[i].jpeg),
                "detail": describe(seen),
            })

    result = build_result(detections, store, images)
    from_whole = build_result(whole, store)
    have = {c["id"] for c in result["cards"]}
    extra = [c for c in from_whole["cards"] if c["id"] not in have]
    result["cards"] += extra
    if len(crops) == 1 and extra and unreadable:
        # One outline found but not recognised, and the whole photo did recognise a
        # card: most likely a close-up where the crop was the card's inner frame.
        unreadable = []
    if not crops:
        result["unmatched"] = from_whole["unmatched"]
    result["unmatched"] += unreadable
    result["detected"] = len(crops) or from_whole["detected"]
    result["cardsFound"] = len(crops)
    if note:
        result["note"] = note
    result["raw"] = {
        "cards": [
            {
                "card": i + 1,
                "corners": crops[i].corners,
                **seen,
                "via": found["via"] if found else None,
                "cardsight": (
                    {"detections": cardsight[i][0], "error": str(cardsight[i][1]) if cardsight[i][1] else None}
                    if i in cardsight else None
                ),
            }
            for i, (found, seen) in enumerate(local)
        ],
        "wholePhoto": {"detections": whole, "error": str(whole_error) if whole_error else None} if jobs else None,
    }
    return result
