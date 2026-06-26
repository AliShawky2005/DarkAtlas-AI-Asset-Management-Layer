from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


# ── Engine ────────────────────────────────────────────────────────────────────
#
# The engine is the low-level connection to the database.
# Think of it as the "factory" that knows how to talk to PostgreSQL.
#
# `echo=settings.DEBUG` — when DEBUG=True, every SQL statement is printed to
# the console.  Very useful while building, turn it off in production.
#
# `pool_pre_ping=True` — before handing you a connection, SQLAlchemy sends
# a cheap "SELECT 1" to check if the connection is still alive.  This catches
# stale connections (e.g., after Postgres restarts) automatically.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)


# ── Session factory ───────────────────────────────────────────────────────────
#
# A "session" is a unit of work: you open one, make changes, and commit.
# We create a *factory* (AsyncSessionLocal) rather than a single session
# because each HTTP request gets its own isolated session.
#
# `expire_on_commit=False` — after you commit, ORM objects stay usable.
# Without this, accessing object attributes after commit would trigger a
# new DB query, which fails in async code because the session is already closed.
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Base class for all ORM models ─────────────────────────────────────────────
#
# Every model (table) we define will inherit from Base.
# SQLAlchemy uses this to track all models and auto-create tables.
class Base(DeclarativeBase):
    """Parent class for every SQLAlchemy ORM model in the project."""
    pass


# ── FastAPI dependency: database session per request ─────────────────────────
#
# FastAPI "dependencies" are reusable functions injected into route handlers.
# Any route that needs a DB session adds `db: AsyncSession = Depends(get_db)`
# to its signature — FastAPI calls get_db(), gives the session to the route,
# and runs the cleanup code after the response is sent.
#
# Pattern:
#   1. Open a session (async context manager)
#   2. yield it to the route handler
#   3. On success: commit (save changes)
#   4. On any exception: rollback (undo changes), then re-raise
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yields an async DB session for a single HTTP request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
