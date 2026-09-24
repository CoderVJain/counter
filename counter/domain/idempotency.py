"""Run a write once per key, however many times the shopkeeper repeats themself.

Voice is lossy: a command gets re-sent, a network hiccup retries, someone says
"sold 2 kg sugar" twice meaning once. Every write tool passes a key, and the
first result is replayed for later calls with that key.

The key row is inserted before the work runs, so a duplicate hits the unique
constraint before it can write anything.
"""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from counter.domain.models import IdempotencyKey


def _stored(db: Session, key: str) -> IdempotencyKey | None:
    return db.execute(select(IdempotencyKey).where(IdempotencyKey.key == key)).scalar_one_or_none()


def once(db: Session, key: str, work: Callable[[], dict]) -> tuple[dict, bool]:
    """Run `work` once for `key`. Returns its result and whether this was a replay.

    If `work` raises, nothing is kept, so the same key can be retried.
    """
    existing = _stored(db, key)
    if existing is not None:
        return existing.result, True

    row = IdempotencyKey(key=key, result={})
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        replayed = _stored(db, key)
        if replayed is None:
            raise
        return replayed.result, True

    result = work()
    row.result = result
    db.flush()
    return result, False
