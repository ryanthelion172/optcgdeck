"""Turns a photo of cards into card ids using the CardSight AI API.

The API key is read from CARDSIGHTAI_API_KEY (put it in backend/.env).
Each scan uses one API call, however many cards are in the photo.
"""

from __future__ import annotations

import re
from io import BytesIO

SEGMENT = "onepiece"

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


def build_result(detections: list[dict], store) -> dict:
    """Groups detections into card counts plus a list of cards we couldn't match."""
    counts: dict[str, dict] = {}
    unmatched: list[dict] = []
    for det in detections:
        card = det.get("card") or {}
        confidence = det.get("confidence") or "Low"
        card_id = match_card(card, store)
        if card_id is None:
            unmatched.append({"label": label(card), "confidence": confidence})
            continue
        entry = counts.setdefault(card_id, {"id": card_id, "count": 0, "confidence": confidence})
        entry["count"] += 1
        # Keep the lowest confidence seen for this card.
        order = ["Low", "Medium", "High"]
        if order.index(confidence) < order.index(entry["confidence"]):
            entry["confidence"] = confidence
    return {"detected": len(detections), "cards": list(counts.values()), "unmatched": unmatched}
