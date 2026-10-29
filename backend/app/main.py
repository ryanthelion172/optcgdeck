from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .cards import CardStore, get_store
from .decks import router as decks_router
from .images import MEDIA_TYPES, close_client, fetch_image
from .scan import ScanError, build_result, identify

# Secrets such as CARDSIGHTAI_API_KEY live in backend/.env, which git ignores.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await close_client()  # close the image download connections on shutdown


app = FastAPI(title="OPTCG Deck Builder API", lifespan=lifespan)

# The Vite dev server runs on a different port during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


app.include_router(decks_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/cards")
def list_cards(request: Request, store: CardStore = Depends(get_store)):
    headers = {"ETag": store.etag, "Cache-Control": "public, max-age=3600"}
    if request.headers.get("if-none-match") == store.etag:
        return Response(status_code=304, headers=headers)
    return Response(
        content=store.json, media_type="application/json", headers=headers
    )


@app.get("/api/cards/{card_id}")
def get_card(card_id: str, store: CardStore = Depends(get_store)) -> dict:
    card = store.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@app.get("/api/cards/{card_id}/image")
async def card_image(card_id: str, store: CardStore = Depends(get_store)):
    card = store.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    path = await fetch_image(card)
    if path is None:
        raise HTTPException(status_code=502, detail="Could not download the card image")
    return FileResponse(
        path,
        media_type=MEDIA_TYPES[path.suffix],
        headers={"Cache-Control": "public, max-age=2592000"},
    )


MAX_PHOTO_BYTES = 15 * 1024 * 1024


@app.post("/api/scan")
def scan_photo(photo: UploadFile = File(...), store: CardStore = Depends(get_store)) -> dict:
    """Identifies the cards in a photo. Uses one CardSight API call."""
    if not (photo.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload a photo.")
    image = photo.file.read(MAX_PHOTO_BYTES + 1)
    if len(image) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="That photo is too large (15 MB max).")
    try:
        detections = identify(image, photo.filename or "photo.jpg", photo.content_type)
    except ScanError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    result = build_result(detections, store)
    # Debugging aid: include CardSight's raw detections so the browser can log them.
    result["raw"] = detections
    return result

