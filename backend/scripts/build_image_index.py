"""Builds the image index that photo scanning uses to recognise cards by their art.

Downloads every card's image (skipping ones already in backend/.image-cache/),
makes a fingerprint of each one (see app/match.py) and saves them all to
backend/.image-index.npz. The running backend picks up the new file on its
next scan, no restart needed.

Run from the backend folder, after scripts/import_cards.py:
    python scripts/build_image_index.py              # base arts and alternate arts
    python scripts/build_image_index.py --base-only  # base arts only (about half the downloads)

The first run downloads a few thousand images, so it takes a while; later runs
only download new cards.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.cards import load_printings  # noqa: E402
from app.db import database_url, session_factory  # noqa: E402
from app.images import close_client, fetch_image  # noqa: E402
from app.match import INDEX_FILE, ImageIndex, fingerprint  # noqa: E402


def images_to_index(printings: list[dict], base_only: bool) -> list[tuple[str, dict]]:
    """(card id, image to fetch) pairs. Alternate arts count as their base card."""
    return [
        (p["card_id"], {"id": p["id"], "image": p["image"]})
        for p in printings
        if p["is_base"] or (not base_only and p["image"])
    ]


async def fetch_all(jobs: list[tuple[str, dict]]) -> list[tuple[str, Path | None]]:
    done = 0

    async def one(card_id: str, image: dict):
        nonlocal done
        path = await fetch_image(image)
        done += 1
        if done % 200 == 0 or done == len(jobs):
            print(f"  {done}/{len(jobs)} images ready")
        return card_id, path

    try:
        return await asyncio.gather(*(one(c, i) for c, i in jobs))
    finally:
        await close_client()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-only", action="store_true", help="skip alternate arts")
    args = parser.parse_args()

    load_dotenv(BACKEND / ".env")
    if database_url() is None:
        print("Set DATABASE_URL in backend/.env first.", file=sys.stderr)
        return 1
    with session_factory()() as db:
        printings = load_printings(db)
    if not printings:
        print("No cards in the database. Run scripts/import_cards.py first.", file=sys.stderr)
        return 1

    jobs = images_to_index(printings, args.base_only)
    print(f"Getting {len(jobs)} card images (cached ones are reused)...")
    results = asyncio.run(fetch_all(jobs))

    ids, vectors, failed = [], [], []
    for (card_id, image), (_, path) in zip(jobs, results):
        img = cv2.imread(str(path), cv2.IMREAD_COLOR) if path else None
        if img is None:
            failed.append(image["id"])
            continue
        ids.append(card_id)
        vectors.append(fingerprint(img))

    if not ids:
        print("No images could be loaded, so no index was saved.", file=sys.stderr)
        return 1
    ImageIndex(ids, np.stack(vectors)).save()
    print(f"Saved fingerprints for {len(ids)} images to {INDEX_FILE.name}.")
    if failed:
        shown = ", ".join(failed[:20]) + (" ..." if len(failed) > 20 else "")
        print(f"{len(failed)} images couldn't be downloaded or read: {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
