# OPTCG Deck Builder

A web deck builder for the One Piece Card Game that works on phones and desktop.

**Now:** search every English card, pick a Leader, build a 50-card deck with live rule checks
and a cost curve, import/export decklists (`4xOP01-016` format), and keep several decks saved
on your device. It can be installed to your home screen as an app.

**Next:** take a photo of a deck and turn it into an editable decklist.

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
uvicorn app.main:app --reload

# Frontend (http://localhost:5173), in a second terminal
cd frontend
npm install
npm run dev
```

The frontend forwards `/api` requests to the backend during development. To try it on your
phone, run `npm run dev -- --host` and open the address it prints from a phone on the same Wi-Fi.

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
generated from the official One Piece Card Game card list. Card images load from the official
site. One Piece Card Game card text and images are © Eiichiro Oda/Shueisha, Toei Animation and
Bandai. This is an unofficial fan project.

## Deck rules checked

- Exactly 1 Leader
- Exactly 50 cards in the main deck
- At most 4 copies of any card number
- Every card shares at least one color with the Leader

Card-specific deck-building exceptions and the banned list are not checked yet.
