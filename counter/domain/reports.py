"""What a day came to: takings, best sellers, and what is still owed.

A shop day runs from midnight to midnight **where the shop is**, not in UTC. Timestamps are stored in
UTC, so the day's edges are worked out in shop time and then compared, which keeps an evening sale on
the day the shopkeeper thinks it happened. Doing this the obvious way would file every sale after
half past eleven under tomorrow.

The comparison is left to the database rather than done in Python, because SQLite hands back
timestamps without their timezone and subtracting one of those from a real time raises.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from counter.domain import ledger
from counter.domain.dates import SHOP_TZ
from counter.domain.models import Item, Sale, SaleLine


@dataclass(frozen=True)
class Seller:
    """One item's contribution to a day."""

    item: Item
    qty_base: int
    total_paise: int


@dataclass(frozen=True)
class DaySummary:
    """Everything worth saying about a day at the counter."""

    day: date
    sale_count: int
    takings_paise: int
    credit_given_paise: int
    top_sellers: list[Seller]
    outstanding_paise: int


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Midnight to midnight in shop time, as moments a database can compare."""
    start = datetime.combine(day, time.min, tzinfo=SHOP_TZ)
    return start, start + timedelta(days=1)


def _on_day(day: date):
    """A filter for sales that happened on that shop day."""
    start, end = day_bounds(day)
    return (Sale.created_at >= start, Sale.created_at < end)


def takings(db: Session, day: date) -> int:
    """Everything sold that day, cash and credit alike, in paise."""
    total = db.execute(select(func.coalesce(func.sum(Sale.total_paise), 0)).where(*_on_day(day))).scalar_one()
    return int(total)


def credit_given(db: Session, day: date) -> int:
    """The part of the day's takings that nobody has paid for yet."""
    total = db.execute(
        select(func.coalesce(func.sum(Sale.total_paise), 0)).where(*_on_day(day), Sale.is_credit)
    ).scalar_one()
    return int(total)


def sale_count(db: Session, day: date) -> int:
    """How many separate sales were rung up."""
    return int(db.execute(select(func.count(Sale.id)).where(*_on_day(day))).scalar_one())


def top_sellers(db: Session, day: date, limit: int = 3) -> list[Seller]:
    """The day's best earners, largest first."""
    rows = db.execute(
        select(
            Item,
            func.sum(SaleLine.qty_base),
            func.sum(SaleLine.line_total_paise),
        )
        .join(SaleLine, SaleLine.item_id == Item.id)
        .join(Sale, Sale.id == SaleLine.sale_id)
        .where(*_on_day(day))
        .group_by(Item.id)
        .order_by(func.sum(SaleLine.line_total_paise).desc(), Item.name)
        .limit(limit)
    ).all()
    return [Seller(item=item, qty_base=int(qty), total_paise=int(paise)) for item, qty, paise in rows]


def for_day(db: Session, day: date) -> DaySummary:
    """The whole day in one object, every figure counted in code."""
    return DaySummary(
        day=day,
        sale_count=sale_count(db, day),
        takings_paise=takings(db, day),
        credit_given_paise=credit_given(db, day),
        top_sellers=top_sellers(db, day),
        outstanding_paise=ledger.outstanding_total(db),
    )
