import json

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .cards import CardStore, get_store

app = FastAPI(title="OPTCG Deck Builder API")

# The Vite dev server runs on a different port during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/cards")
def list_cards(request: Request, store: CardStore = Depends(get_store)):
    headers = {"ETag": store.etag, "Cache-Control": "public, max-age=3600"}
    if request.headers.get("if-none-match") == store.etag:
        return Response(status_code=304, headers=headers)
    return Response(
        content=store_json(store), media_type="application/json", headers=headers
    )


@app.get("/api/cards/{card_id}")
def get_card(card_id: str, store: CardStore = Depends(get_store)) -> dict:
    card = store.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


_json_cache: dict[str, bytes] = {}


def store_json(store: CardStore) -> bytes:
    """Serialise the full card list once per data version."""
    if store.etag not in _json_cache:
        _json_cache.clear()
        _json_cache[store.etag] = json.dumps(
            store.cards, ensure_ascii=False, separators=(",", ":")
        ).encode()
    return _json_cache[store.etag]
