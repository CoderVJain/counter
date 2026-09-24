"""Stock levels, derived from the append-only movement log."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from counter.domain.models import Item, StockMovement, now


class InsufficientStock(Exception):
    """Raised instead of letting stock go negative. Carries what is actually there."""

    def __init__(self, item: Item, wanted_base: int, have_base: int):
        self.item = item
        self.wanted_base = wanted_base
        self.have_base = have_base
        super().__init__(
            f"{item.name}: wanted {wanted_base}{item.base_unit}, have {have_base}{item.base_unit}"
        )


@dataclass(frozen=True)
class StockLevel:
    item: Item
    on_hand_base: int
    days_of_stock: float | None  # None when there is no sales history to judge by


def on_hand(db: Session, item_id: int) -> int:
    """Current quantity in base units."""
    total = db.execute(
        select(func.coalesce(func.sum(StockMovement.delta_base), 0)).where(StockMovement.item_id == item_id)
    ).scalar_one()
    return int(total)


def move(db: Session, item: Item, delta_base: int, reason: str, ref: str | None = None) -> StockMovement:
    """Append a movement. Refuses to take out more than is on hand."""
    if delta_base < 0:
        have = on_hand(db, item.id)
        if have + delta_base < 0:
            raise InsufficientStock(item, -delta_base, have)

    movement = StockMovement(item_id=item.id, delta_base=delta_base, reason=reason, ref=ref)
    db.add(movement)
    db.flush()
    return movement


def daily_sales_rate(db: Session, item_id: int, window_days: int = 14) -> float | None:
    """Average base units sold per day over the window. None if nothing was sold."""
    since = now() - timedelta(days=window_days)
    sold = db.execute(
        select(func.coalesce(func.sum(StockMovement.delta_base), 0)).where(
            StockMovement.item_id == item_id,
            StockMovement.reason == "sale",
            StockMovement.created_at >= since,
        )
    ).scalar_one()
    if not sold:
        return None
    return abs(int(sold)) / window_days


def level(db: Session, item: Item, window_days: int = 14) -> StockLevel:
    """Quantity plus a days-of-stock estimate for the briefing."""
    have = on_hand(db, item.id)
    rate = daily_sales_rate(db, item.id, window_days)
    days = round(have / rate, 1) if rate else None
    return StockLevel(item=item, on_hand_base=have, days_of_stock=days)


def below_reorder_level(db: Session) -> list[StockLevel]:
    """Items at or under their reorder level, worst first."""
    levels = [level(db, item) for item in db.execute(select(Item)).scalars()]
    low = [lv for lv in levels if lv.on_hand_base <= lv.item.reorder_level_base]
    return sorted(low, key=lambda lv: lv.on_hand_base - lv.item.reorder_level_base)
