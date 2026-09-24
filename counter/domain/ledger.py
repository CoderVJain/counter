"""Customer credit: what is owed, what is due, and applying payments.

A credit sale writes a positive entry, a payment writes a negative one, so a
balance is a sum and can never drift. Which specific entries a payment settles
is worked out on read, oldest due date first, the way a shopkeeper would.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from counter.domain.models import CreditEntry, Customer


class Overpayment(Exception):
    """A payment larger than the balance. Ask rather than create a phantom advance."""

    def __init__(self, customer: Customer, paid_paise: int, balance_paise: int):
        self.customer = customer
        self.paid_paise = paid_paise
        self.balance_paise = balance_paise
        super().__init__(f"{customer.name} paid {paid_paise} but owes {balance_paise}")


@dataclass(frozen=True)
class Due:
    """One unsettled credit entry and what remains on it."""

    entry: CreditEntry
    remaining_paise: int

    @property
    def due_date(self) -> date | None:
        return self.entry.due_date


def balance(db: Session, customer_id: int) -> int:
    """What the customer owes right now, in paise. Never negative in practice."""
    total = db.execute(
        select(func.coalesce(func.sum(CreditEntry.amount_paise), 0)).where(
            CreditEntry.customer_id == customer_id
        )
    ).scalar_one()
    return int(total)


def outstanding_total(db: Session) -> int:
    """Everything owed by everyone, for the daily summary."""
    total = db.execute(select(func.coalesce(func.sum(CreditEntry.amount_paise), 0))).scalar_one()
    return int(total)


def add_credit(
    db: Session,
    customer: Customer,
    amount_paise: int,
    due_date: date | None = None,
    sale_id: int | None = None,
) -> CreditEntry:
    """Record that a customer owes money."""
    entry = CreditEntry(
        customer_id=customer.id,
        sale_id=sale_id,
        amount_paise=amount_paise,
        due_date=due_date,
    )
    db.add(entry)
    db.flush()
    return entry


def record_payment(db: Session, customer: Customer, amount_paise: int) -> CreditEntry:
    """Apply a payment against the balance. Refuses to overpay."""
    owed = balance(db, customer.id)
    if amount_paise > owed:
        raise Overpayment(customer, amount_paise, owed)

    entry = CreditEntry(customer_id=customer.id, amount_paise=-amount_paise)
    db.add(entry)
    db.flush()
    return entry


def _sort_key(entry: CreditEntry) -> tuple[int, date, int]:
    """Undated entries settle last; otherwise oldest due date first."""
    return (1, date.max, entry.id) if entry.due_date is None else (0, entry.due_date, entry.id)


def open_dues(db: Session, customer_id: int) -> list[Due]:
    """Unsettled charges for one customer, with payments applied oldest first."""
    entries = list(db.execute(select(CreditEntry).where(CreditEntry.customer_id == customer_id)).scalars())
    charges = sorted((e for e in entries if e.amount_paise > 0), key=_sort_key)
    pot = sum(-e.amount_paise for e in entries if e.amount_paise < 0)

    dues: list[Due] = []
    for charge in charges:
        settled = min(pot, charge.amount_paise)
        pot -= settled
        remaining = charge.amount_paise - settled
        if remaining:
            dues.append(Due(entry=charge, remaining_paise=remaining))
    return dues


def due_by(db: Session, on_date: date) -> list[Due]:
    """Everything due on or before a date, across all customers, soonest first."""
    customer_ids = db.execute(select(Customer.id)).scalars()
    dues = [due for cid in customer_ids for due in open_dues(db, cid)]
    ripe = [d for d in dues if d.due_date is not None and d.due_date <= on_date]
    return sorted(ripe, key=lambda d: d.due_date)
