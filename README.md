# OPTCG Deck Builder

A web deck builder for the One Piece Card Game that works on phones and desktop.

**Now:** browse every English card by set and color, pick a Leader, build a 50-card deck with live rule checks
and a cost curve, import/export decklists (`4xOP01-016` format), and keep several decks saved
in a Postgres database. It can be installed to your home screen as an app.

**Create deck from photo:** lay out one copy of each card, take or upload a photo, check what was
recognised, set the counts, and turn it into a deck. The backend finds each card in the photo with
OpenCV and crops it. Each crop is then identified, trying in order:

1. **Set code:** reads the card number printed in the bottom-right corner (RapidOCR, runs locally).
2. **Image match:** compares the card's art with every card's official image (runs locally; needs
   the image index, see below). When that match is weak or missing, the card's **name** printed at
   the bottom is read (RapidOCR again), and the art is compared with only the cards that have that
   name. This works for English cards only.
3. **CardSight:** the [CardSight AI](https://cardsight.ai) API, only for cards the first two
   couldn't place.

The scan results say which step found each card, and show the cut-out picture of any card that
wasn't identified, with what the number reader and image match saw. Photos work best with the cards
flat, not overlapping, on a plain background that contrasts with them.

## Project layout

```
backend/    Python FastAPI app: card data, card images, photo scanning and saved decks
  migrations/              Database tables (Alembic)
  scripts/import_cards.py  Downloads the English card list into the database
frontend/   React + TypeScript + Vite + Tailwind app
```

## Running it locally

You need Python 3.12+ and Node 20+.

```bash
# Database (local Postgres in Docker), from the repo root
docker compose up -d

# Backend (http://127.0.0.1:8000)
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env               # add your CardSight key; DATABASE_URL already points at the local database
python -m alembic upgrade head     # create the tables
python scripts/import_cards.py     # load the cards (about 30 seconds)
python scripts/build_image_index.py  # card images for scanning (first run downloads a few thousand images)
uvicorn app.main:app --reload

# Frontend (http://localhost:5173), in a second terminal
cd frontend
npm install
npm run dev
```

The frontend forwards `/api` requests to the backend during development. To try it on your
phone, run `npm run dev -- --host` and open the address it prints from a phone on the same Wi-Fi.

### Database (Postgres)

The app needs a Postgres database. For development it runs on your own computer, so nothing is
stored online. It holds these tables:

- `sets`: each pack or deck cards come in (code like `OP-01`, name, kind, release date).
- `cards`: one row per card number (e.g. `OP01-016`) with its game text, filled by
  `scripts/import_cards.py`. `set_id` points at the set it first came out in.
- `card_printings`: every printed version of a card, the base art and each alternate art
  (e.g. `OP01-016_p1`), with its image. Photo scanning uses these; the app is only sent base arts.
  Besides the English (North America/Europe) list, the import adds alternate arts that only the
  other regions' lists have (English Asia, Japanese, Chinese, Thai, French), such as Asia-only
  "Limited Product Card" arts. `language` says which list each printing came from.
- `card_names`: each card's name in other languages, keyed by card number (Japanese for now, e.g.
  `OP01-016` → ナミ). Card numbers are the same in every language, so `scripts/import_cards.py`
  fills it from the Japanese card list in the same dataset. Sets that aren't in the Japanese list
  yet (at the moment OP18 and EB05) have no Japanese names until a later import.
- `users`: accounts (email, display name, password hash). Sign-up and sign-in aren't built yet.
- `decks`: each deck's name, Leader and owner.
- `deck_cards`: how many copies of each card a deck has.

Decks point at cards with foreign keys, so they depend only on our copy, never on the outside
source. The import adds new cards and updates changed ones but never deletes a card, and the
database refuses to delete a card that a deck uses.

A deck's owner is a user account (`owner_id`), or, for decks made without an account, an "owner
key": each browser makes a random key (the only thing the app keeps in the browser), and the
database keeps only a hash of it, so your decks show up in the browser that made them. Until
accounts are built, every deck uses an owner key, and no names or emails are stored.

1. Start Postgres. The easiest way is Docker: `docker compose up -d` from the repo root starts it
   in the background and keeps your data between restarts (`docker compose down` stops it).
   Without Docker, install Postgres (on Ubuntu or WSL: `sudo apt install postgresql`, then
   `sudo service postgresql start`) and create the user and database that `.env.example` uses:
   ```bash
   sudo -u postgres psql -c "CREATE USER optcg WITH PASSWORD 'optcg';" \
     -c "CREATE DATABASE optcg OWNER optcg ENCODING 'UTF8' TEMPLATE template0;"
   ```
   The `ENCODING 'UTF8'` part matters: without it, some systems create the database as
   `SQL_ASCII`, and the backend fails with "cannot use a string pattern on a bytes-like object".
2. Create the tables: `cd backend && python -m alembic upgrade head`.
3. Load the cards: `python scripts/import_cards.py`.

When the app is deployed later, point `DATABASE_URL` at a hosted Postgres (for example Neon)
and run steps 2 and 3 against it. No code changes are needed.

When the tables change later, a new migration goes in `backend/migrations/versions/` and the
same `python -m alembic upgrade head` command applies it.

`backend/.env` holds your `CARDSIGHTAI_API_KEY` and `DATABASE_URL`. Git ignores it, so it never goes to GitHub.
Everything except photo scanning works without the CardSight key.

## Tests

```bash
cd backend && pytest -q          # set TEST_DATABASE_URL to an empty Postgres to include the database tests
cd frontend && npm test && npm run lint && npm run build
```

## Updating card data

```bash
cd backend && python scripts/import_cards.py
```

Then restart the backend so it picks up the new cards.
Run `python scripts/build_image_index.py` afterwards too, so photo scanning can recognise the new
cards by their art (it only downloads images it doesn't have yet).

**Upgrading an existing setup:** scanning now uses `opencv-python` in place of
`opencv-python-headless`. Run `pip uninstall -y opencv-python-headless` and then
`pip install -r requirements-dev.txt`, since the two packages clash when both are installed.
Then run `python -m alembic upgrade head` and `python scripts/import_cards.py` to move to the new
tables (sets and card printings) and fill in the sets.

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
