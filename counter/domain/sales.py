"""Write a sale: the rows, the stock that left the shelf, and the debt if it was not paid for.

This is the only place a sale is written. Until now the one example lived inline in `seed.py`, which
meant the demo data and the real thing could drift apart.

Three things happen together and must not come apart: the sale is recorded, the stock goes down, and
a credit sale becomes money owed. If any part refuses - most often because there is not enough on the
shelf - the caller's session rolls back and none of it happened. A sale that took stock without
recording the debt would quietly cost the shopkeeper the whole basket.

Money is recomputed here from the item and the quantity rather than trusted from the caller, so the
price on the shelf is always the price charged.
"""

from datetime import date

from sqlalchemy.orm import Session

from counter.domain import audit, inventory, ledger, units
from counter.domain.models import Customer, Item, Sale, SaleLine

Line = tuple[Item, int]  # the item, and how much of it in base units


class NothingToSell(Exception):
    """A sale with no lines. Refused rather than written as an empty row."""


class CreditWithoutCustomer(Exception):
    """Credit with nobody to owe it. Refused, because an unowned debt is never collected."""


def record(
    db: Session,
    lines: list[Line],
    customer: Customer | None = None,
    is_credit: bool = False,
    due_date: date | None = None,
) -> Sale:
    """Record one sale. Takes the stock out and, on credit, adds what is owed."""
    if not lines:
        raise NothingToSell("a sale needs at least one item")

    sale = Sale(
        customer_id=customer.id if customer else None,
        is_credit=is_credit,
        total_paise=0,
    )
    db.add(sale)
    db.flush()

    total = 0
    for item, qty_base in lines:
        line_total = units.line_total_paise(item, qty_base)
        total += line_total
        db.add(
            SaleLine(
                sale_id=sale.id,
                item_id=item.id,
                qty_base=qty_base,
                line_total_paise=line_total,
            )
        )
        # Refuses if the shelf cannot cover it, which aborts the whole sale.
        inventory.move(db, item, -qty_base, "sale", ref=f"sale:{sale.id}")

    sale.total_paise = total

    if is_credit:
        if customer is None:
            raise CreditWithoutCustomer("a credit sale needs a customer")
        ledger.add_credit(db, customer, total, due_date=due_date, sale_id=sale.id)

    audit.record(
        db,
        audit.SALE,
        {
            "sale_id": sale.id,
            "lines": [{"item_id": item.id, "qty_base": qty} for item, qty in lines],
            "total_paise": total,
            "customer_id": customer.id if customer else None,
            "is_credit": is_credit,
        },
    )
    db.flush()
    return sale
