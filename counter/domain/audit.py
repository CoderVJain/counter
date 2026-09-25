"""One row per write, so every number the shop hears can be traced back to its cause.

A shopkeeper who is told they are owed Rs 700 will eventually ask why. Sales, payments and orders are
each derived from other rows, so the trail exists in principle, but only this table says what the
assistant was asked to do and when, in one place and in order.

The row is written by the same session as the write it describes, so it rolls back with it. An audit
line for a sale that never happened would be worse than none.

Two rules about what goes in. `detail` holds identifiers and amounts, never a sentence. The spoken
sentence is passed separately and only when the caller means to keep it, because it carries a
customer's name and their debts, and this table is not a place to spread those by accident.
"""

from sqlalchemy.orm import Session

from counter.domain.models import AuditLog

MAX_UTTERANCE = 500

SALE = "sale.record"
PAYMENT = "credit.payment"
ORDER_CONFIRMED = "order.confirm"
ORDER_SENT = "order.sent"


def record(db: Session, action: str, detail: dict, utterance: str | None = None) -> AuditLog:
    """Write one audit line. Called from inside the write it describes, never after it."""
    row = AuditLog(
        action=action,
        detail=detail,
        utterance=utterance[:MAX_UTTERANCE] if utterance else None,
    )
    db.add(row)
    db.flush()
    return row


def trail(db: Session, limit: int = 20) -> list[AuditLog]:
    """The most recent writes, newest first, for answering "why does it say that?"."""
    return list(db.query(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit))
