"""Supplier orders: draft, confirm, send.

Ordering spends the shopkeeper's money, so it is deliberately two-step. A draft
is built and read back; only an explicit confirmation moves it forward. Stock is
not touched here - goods that have been ordered have not arrived, and stock only
moves when they do.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from counter.domain import audit, inventory
from counter.domain.models import Item, Supplier, SupplierOrder, SupplierOrderLine

DRAFT = "draft"
CONFIRMED = "confirmed"
SENT = "sent"


class EmptyOrder(Exception):
    """An order with no lines. Ask what to order instead of sending nothing."""


class UnknownOrder(Exception):
    """No order with that id. The shopkeeper misremembered or misspoke it."""


class InvalidTransition(Exception):
    """A confirm or send that does not follow from the order's current status."""

    def __init__(self, order: SupplierOrder, wanted: str):
        self.order = order
        self.wanted = wanted
        super().__init__(f"order {order.id} is {order.status}, cannot become {wanted}")


@dataclass(frozen=True)
class Suggestion:
    """A proposed reorder line, with the numbers that justify it."""

    item: Item
    qty_base: int
    on_hand_base: int
    days_of_stock: float | None


def suggest_reorder(db: Session) -> list[Suggestion]:
    """Top every low item back up to twice its reorder level."""
    suggestions = []
    for level in inventory.below_reorder_level(db):
        target = level.item.reorder_level_base * 2
        qty = target - level.on_hand_base
        if qty > 0:
            suggestions.append(
                Suggestion(
                    item=level.item,
                    qty_base=qty,
                    on_hand_base=level.on_hand_base,
                    days_of_stock=level.days_of_stock,
                )
            )
    return suggestions


def create_draft(db: Session, supplier: Supplier, lines: list[tuple[Item, int]]) -> SupplierOrder:
    """Build a draft order. Nothing leaves the shop until it is confirmed."""
    if not lines:
        raise EmptyOrder(supplier.name)

    order = SupplierOrder(supplier_id=supplier.id, status=DRAFT)
    db.add(order)
    db.flush()

    for item, qty_base in lines:
        db.add(SupplierOrderLine(order_id=order.id, item_id=item.id, qty_base=qty_base))
    db.flush()
    return order


def confirm(db: Session, order_id: int) -> SupplierOrder:
    """Move a draft to confirmed. Only a draft may be confirmed."""
    order = db.get(SupplierOrder, order_id)
    if order is None:
        raise UnknownOrder(order_id)
    if order.status != DRAFT:
        raise InvalidTransition(order, CONFIRMED)

    order.status = CONFIRMED
    db.flush()
    audit.record(db, audit.ORDER_CONFIRMED, {"order_id": order.id, "supplier_id": order.supplier_id})
    return order


def mark_sent(db: Session, order_id: int) -> SupplierOrder:
    """Record that the simulated supplier accepted the order."""
    order = db.get(SupplierOrder, order_id)
    if order is None:
        raise UnknownOrder(order_id)
    if order.status != CONFIRMED:
        raise InvalidTransition(order, SENT)

    order.status = SENT
    db.flush()
    audit.record(db, audit.ORDER_SENT, {"order_id": order.id, "supplier_id": order.supplier_id})
    return order


def drafts(db: Session) -> list[SupplierOrder]:
    """Outstanding drafts, oldest first, so a confirmation can find its order."""
    return list(
        db.execute(
            select(SupplierOrder).where(SupplierOrder.status == DRAFT).order_by(SupplierOrder.id)
        ).scalars()
    )
