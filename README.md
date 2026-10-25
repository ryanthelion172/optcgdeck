# OPTCG Deck Builder

A web deck builder for the One Piece Card Game that works on phones and desktop.

**Now:** browse every English card by set and color, pick a Leader, build a 50-card deck with live rule checks
and a cost curve, import/export decklists (`4xOP01-016` format), and keep several decks saved
on your device. It can be installed to your home screen as an app.

**Create deck from photo:** take or upload a photo of your cards, check what was recognised,
fix any counts, and turn it into a deck. Scanning uses the [CardSight AI](https://cardsight.ai)
API (one API call per photo).

## Project layout

```
backend/    Python FastAPI app: serves card data (and later, photo scanning)
  data/cards.json          English card database
  scripts/import_cards.py  Refreshes cards.json when new sets come out
frontend/   React + TypeScript + Vite + Tailwind app
```

## Running it locally

You need Python 3.12+ and Node 20+.

```bash
# Backend (http://127.0.0.1:8000)
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env               # then add your CardSight API key to .env
uvicorn app.main:app --reload

# Frontend (http://localhost:5173), in a second terminal
cd frontend
npm install
npm run dev
```

The frontend forwards `/api` requests to the backend during development. To try it on your
phone, run `npm run dev -- --host` and open the address it prints from a phone on the same Wi-Fi.

`backend/.env` holds your `CARDSIGHTAI_API_KEY`. Git ignores it, so it never goes to GitHub.
Everything except photo scanning works without a key.

## Tests

```bash
cd backend && pytest -q
cd frontend && npm test && npm run lint && npm run build
```

## Updating card data

```bash
cd backend && python scripts/import_cards.py
```

Card data comes from the [Punk Records](https://github.com/buhbbl/punk-records) dataset, which is
generated from the official One Piece Card Game card list. Card images are downloaded by the
backend the first time they're shown (official site first, Limitless TCG as a backup) and saved in
`backend/.image-cache/`. Only base arts are downloaded for now. If an image won't load, the backend
terminal shows why. One Piece Card Game card text and images are © Eiichiro Oda/Shueisha, Toei Animation and
Bandai. This is an unofficial fan project.

## Deck rules checked

- Exactly 1 Leader
- Exactly 50 cards in the main deck
- At most 4 copies of any card number (OP08-072 and OP16-042 allow any number)
- Every card shares at least one color with the Leader

Other card-specific deck-building exceptions and the banned list are not checked yet.
