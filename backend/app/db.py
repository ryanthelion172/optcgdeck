"""Database connection. Set DATABASE_URL in backend/.env (see .env.example)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def database_url() -> str | None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    # Connection strings start "postgresql://"; tell SQLAlchemy to use the psycopg 3 driver.
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = database_url()
    if url is None:
        raise RuntimeError("DATABASE_URL is not set")
    # pool_pre_ping reconnects cleanly if the database restarted or dropped an idle connection.
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


@lru_cache(maxsize=1)
def session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, closed afterwards."""
    if database_url() is None:
        raise HTTPException(status_code=503, detail="Set DATABASE_URL in backend/.env to save decks online.")
    with session_factory()() as session:
        yield session
