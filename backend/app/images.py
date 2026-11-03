"""Serves card images through the backend.

Browsers often can't load card art straight from the official site (it blocks
images embedded on other sites), so the backend downloads each image once,
saves it to a local cache folder and serves it from there.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path

import httpx

log = logging.getLogger("uvicorn.error")

CACHE_DIR = Path(__file__).resolve().parent.parent / ".image-cache"

# Sent with every download so the request looks like it came from the card list page.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Referer": "https://en.onepiece-cardgame.com/cardlist/",
    "Accept": "image/avif,image/webp,image/png,image/*;q=0.8",
}

SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
MEDIA_TYPES = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg"}


def source_urls(card: dict) -> list[str]:
    """Places to try, in order: the official site, then the Limitless TCG CDN."""
    urls = []
    if card.get("image"):
        urls.append(card["image"])
    set_code = card["id"].split("-")[0]
    urls.append(
        f"https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/one-piece/{set_code}/{card['id']}_EN.webp"
    )
    return urls


def cached_file(card_id: str) -> Path | None:
    for ext in MEDIA_TYPES:
        path = CACHE_DIR / f"{card_id}{ext}"
        if path.exists():
            return path
    return None


def extension_for(content_type: str, url: str) -> str:
    if "webp" in content_type or url.split("?")[0].endswith(".webp"):
        return ".webp"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    return ".png"


_client: httpx.AsyncClient | None = None

# The card grid asks for dozens of images at once. Download at most a few at a
# time so the image sites don't throttle us, and only once per card even when
# several requests for the same card arrive together.
_download_slots = asyncio.Semaphore(6)
_card_locks: dict[str, asyncio.Lock] = {}


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True)
    return _client


async def fetch_image(card: dict) -> Path | None:
    """Returns a local file with the card's image, downloading it if needed."""
    card_id = card["id"]
    if not SAFE_NAME.match(card_id):
        return None
    if path := cached_file(card_id):
        return path

    # One small lock per card id (at most a few thousand, so they're kept).
    async with _card_locks.setdefault(card_id, asyncio.Lock()):
        # Another request may have finished the download while we waited.
        if path := cached_file(card_id):
            return path
        async with _download_slots:
            return await _download(card)


async def _download(card: dict) -> Path | None:
    card_id = card["id"]
    client = get_client()
    for url in source_urls(card):
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            log.warning("Image download failed for %s from %s: %s", card_id, url, exc)
            continue
        content_type = resp.headers.get("content-type", "")
        if resp.status_code != 200 or not content_type.startswith("image/"):
            log.warning(
                "Image download failed for %s from %s: HTTP %s (%s)",
                card_id, url, resp.status_code, content_type or "no content type",
            )
            continue
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = CACHE_DIR / f"{card_id}{extension_for(content_type, url)}"
        # A unique temp name, then an atomic rename, so a half-written file is never served.
        tmp = CACHE_DIR / f"{card_id}.{uuid.uuid4().hex}.part"
        tmp.write_bytes(resp.content)
        tmp.replace(path)
        return path
    return None


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
