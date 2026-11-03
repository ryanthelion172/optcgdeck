"""Shared test setup.

Most tests use a small sample of real cards (tests/sample_cards.json) in
place of the database. Tests that need Postgres use the `database` fixture,
which runs when TEST_DATABASE_URL points at an empty database (CI sets it)
and skips otherwise. That database is wiped and migrated from scratch.
"""

import json
import os
from pathlib import Path

import pytest

from app.cards import CardStore, get_store, reload_store
from app.main import app

SAMPLE_CARDS = json.loads((Path(__file__).parent / "sample_cards.json").read_text())
TEST_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def sample_store():
    store = CardStore(SAMPLE_CARDS)
    app.dependency_overrides[get_store] = lambda: store
    yield store
    app.dependency_overrides.pop(get_store, None)


@pytest.fixture(scope="session")
def database():
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    from alembic import command
    from alembic.config import Config

    from app import db
    from app.cards import upsert_cards

    os.environ["DATABASE_URL"] = TEST_URL
    db.get_engine.cache_clear()
    db.session_factory.cache_clear()
    reload_store()
    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")  # also checks the migrations work
    with db.session_factory()() as session:
        upsert_cards(session, SAMPLE_CARDS)
    yield db
    db.get_engine().dispose()
