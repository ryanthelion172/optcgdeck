"""Loads the card database from data/cards.json once and keeps it in memory."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "cards.json"


class CardStore:
    def __init__(self, path: Path = DATA_FILE) -> None:
        raw = path.read_bytes()
        self.cards: list[dict] = json.loads(raw)
        self.by_id: dict[str, dict] = {c["id"]: c for c in self.cards}
        # Changes whenever the data file changes, so browsers can cache it.
        self.etag = '"' + hashlib.sha256(raw).hexdigest()[:16] + '"'

    def get(self, card_id: str) -> dict | None:
        return self.by_id.get(card_id.upper())


@lru_cache(maxsize=1)
def get_store() -> CardStore:
    return CardStore()
