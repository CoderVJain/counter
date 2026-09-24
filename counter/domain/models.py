"""Database schema.

Two conventions hold everywhere: quantities are integer counts of an item's
base unit (g, ml, piece), and money is integer paise. No floats, no Decimals.
Stock is derived from stock_movement, which is append-only.
"""

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Shop(Base):
    __tablename__ = "shop"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))


class Item(Base):
    """A sellable line. `unit` is what the shopkeeper says, `base_unit` is what we store."""

    __tablename__ = "item"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    unit: Mapped[str] = mapped_column(String(16))  # kg, litre, packet, piece, dozen
    base_unit: Mapped[str] = mapped_column(String(8))  # g, ml, piece
    base_per_unit: Mapped[int] = mapped_column(Integer)  # 1000 for kg, 1 for packet
    price_paise: Mapped[int] = mapped_column(Integer)  # per `unit`
    reorder_level_base: Mapped[int] = mapped_column(Integer, default=0)


class StockMovement(Base):
    """Append-only. Positive delta is stock in, negative is stock out."""

    __tablename__ = "stock_movement"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"), index=True)
    delta_base: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(32))  # sale, purchase, correction, opening
    ref: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    item: Mapped[Item] = relationship()


class Customer(Base):
    __tablename__ = "customer"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    nicknames: Mapped[list[str]] = mapped_column(JSON, default=list)


class Sale(Base):
    __tablename__ = "sale"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customer.id"))
    is_credit: Mapped[bool] = mapped_column(default=False)
    total_paise: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    lines: Mapped[list["SaleLine"]] = relationship(back_populates="sale")
    customer: Mapped[Customer | None] = relationship()


class SaleLine(Base):
    __tablename__ = "sale_line"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sale.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"))
    qty_base: Mapped[int] = mapped_column(Integer)
    line_total_paise: Mapped[int] = mapped_column(Integer)

    sale: Mapped[Sale] = relationship(back_populates="lines")
    item: Mapped[Item] = relationship()


class CreditEntry(Base):
    """Money owed by a customer. A payment is a negative amount."""

    __tablename__ = "credit_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"), index=True)
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sale.id"))
    amount_paise: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    customer: Mapped[Customer] = relationship()


class Supplier(Base):
    __tablename__ = "supplier"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)


class SupplierOrder(Base):
    __tablename__ = "supplier_order"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("supplier.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft, confirmed, sent
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    lines: Mapped[list["SupplierOrderLine"]] = relationship(back_populates="order")
    supplier: Mapped[Supplier] = relationship()


class SupplierOrderLine(Base):
    __tablename__ = "supplier_order_line"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("supplier_order.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"))
    qty_base: Mapped[int] = mapped_column(Integer)

    order: Mapped[SupplierOrder] = relationship(back_populates="lines")
    item: Mapped[Item] = relationship()


class AuditLog(Base):
    """One row per write, so every spoken number can be traced to its cause."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(48))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    utterance: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class IdempotencyKey(Base):
    """A repeated voice command must never write twice. Stores the first result."""

    __tablename__ = "idempotency_key"
    __table_args__ = (UniqueConstraint("key", name="uq_idempotency_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(128), index=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
