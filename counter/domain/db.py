"""Engine and session factory. SQLite locally, Postgres when DATABASE_URL is set."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from counter.config import settings

DEFAULT_URL = "sqlite:///counter.db"


def engine_url() -> str:
    """Neon when configured, otherwise a local SQLite file."""
    return settings().database_url or DEFAULT_URL


_engine = create_engine(engine_url(), future=True)
SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)


def engine():
    return _engine


@contextmanager
def session() -> Iterator[Session]:
    """One unit of work. Commits on success, rolls back on error."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
