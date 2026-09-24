"""Seed a demo shop: items, customers, suppliers, opening stock, recent sales.

Product names are generic on purpose - the hackathon rules forbid third-party
trademarks in the repo or the video - but the aliases are what a shopkeeper
actually says at the counter.

    uv run python -m counter.seed [--reset]
"""

import argparse
import random
from datetime import date, timedelta

from sqlalchemy import select

from counter.domain import inventory, ledger
from counter.domain.db import engine, session
from counter.domain.models import (
    Base,
    Customer,
    Item,
    Sale,
    SaleLine,
    Shop,
    Supplier,
    now,
)
from counter.domain.units import line_total_paise

# name, aliases, unit, base_unit, base_per_unit, price_paise, reorder_level_base
ITEMS = [
    ("sugar", ["cheeni", "shakkar"], "kg", "g", 1000, 4500, 5_000),
    ("wheat flour", ["atta", "gehun ka atta"], "kg", "g", 1000, 4200, 10_000),
    ("rice", ["chawal"], "kg", "g", 1000, 6000, 10_000),
    ("toor dal", ["arhar dal", "dal"], "kg", "g", 1000, 14000, 4_000),
    ("moong dal", ["moong"], "kg", "g", 1000, 12500, 3_000),
    ("chana dal", ["chana"], "kg", "g", 1000, 9500, 3_000),
    ("rajma", ["kidney beans"], "kg", "g", 1000, 15000, 2_000),
    ("salt", ["namak"], "kg", "g", 1000, 2500, 3_000),
    ("mustard oil", ["sarson ka tel", "tel"], "litre", "ml", 1000, 18000, 4_000),
    ("refined oil", ["refined", "cooking oil"], "litre", "ml", 1000, 15500, 4_000),
    ("ghee", ["desi ghee"], "litre", "ml", 1000, 62000, 2_000),
    ("toned milk", ["doodh", "milk"], "litre", "ml", 1000, 6000, 10_000),
    ("curd", ["dahi"], "kg", "g", 1000, 8000, 2_000),
    ("paneer", ["cottage cheese"], "kg", "g", 1000, 40000, 1_000),
    ("tea leaves", ["chai patti", "chai"], "kg", "g", 1000, 48000, 1_000),
    ("coffee powder", ["coffee"], "kg", "g", 1000, 90000, 500),
    ("turmeric powder", ["haldi"], "kg", "g", 1000, 32000, 1_000),
    ("chilli powder", ["mirchi", "lal mirch"], "kg", "g", 1000, 36000, 1_000),
    ("coriander powder", ["dhaniya"], "kg", "g", 1000, 28000, 1_000),
    ("cumin seeds", ["jeera"], "kg", "g", 1000, 52000, 500),
    ("mustard seeds", ["sarson"], "kg", "g", 1000, 18000, 500),
    ("gram flour", ["besan"], "kg", "g", 1000, 9000, 3_000),
    ("semolina", ["sooji", "rava"], "kg", "g", 1000, 5500, 2_000),
    ("poha", ["chiwda"], "kg", "g", 1000, 6000, 2_000),
    ("glucose biscuits", ["biscuit", "glucose"], "packet", "piece", 1, 1000, 30),
    ("cream biscuits", ["cream biscuit"], "packet", "piece", 1, 2000, 20),
    ("instant noodles", ["noodles"], "packet", "piece", 1, 1400, 40),
    ("bread", ["double roti"], "packet", "piece", 1, 4500, 10),
    ("rusk", ["toast"], "packet", "piece", 1, 3500, 10),
    ("potato chips", ["chips"], "packet", "piece", 1, 2000, 25),
    ("namkeen mixture", ["namkeen", "mixture"], "packet", "piece", 1, 5000, 15),
    ("soap bar", ["sabun", "soap"], "piece", "piece", 1, 3500, 20),
    ("detergent powder", ["surf", "washing powder"], "kg", "g", 1000, 12000, 3_000),
    ("shampoo sachet", ["shampoo"], "piece", "piece", 1, 300, 50),
    ("toothpaste", ["manjan", "paste"], "piece", "piece", 1, 5500, 12),
    ("matchbox", ["machis"], "piece", "piece", 1, 200, 40),
    ("candle", ["mombatti"], "piece", "piece", 1, 1000, 20),
    ("incense sticks", ["agarbatti"], "packet", "piece", 1, 3000, 15),
    ("eggs", ["anda", "ande"], "piece", "piece", 1, 700, 30),
    ("cooking gas lighter", ["lighter"], "piece", "piece", 1, 6000, 5),
]

CUSTOMERS = [
    ("Sharma ji", ["sharma", "sharmaji"]),
    ("Gupta ji", ["gupta", "guptaji"]),
    ("Verma bhai", ["verma"]),
    ("Anita didi", ["anita"]),
    ("Rakesh", ["rakesh bhai"]),
    ("Sunita ji", ["sunita"]),
    ("Imran bhai", ["imran"]),
    ("Kamla aunty", ["kamla"]),
    ("Deepak", ["deepak bhai"]),
    ("Farida ji", ["farida"]),
]

SUPPLIERS = [
    ("Krishna Wholesale", ["krishna", "krishna traders"]),
    ("Ramesh Distributors", ["ramesh", "ramesh ji"]),
]


def _create_catalog(db) -> tuple[list[Item], list[Customer]]:
    db.add(Shop(name="Sharma General Store"))

    items = [
        Item(
            name=name,
            aliases=aliases,
            unit=unit,
            base_unit=base_unit,
            base_per_unit=base_per_unit,
            price_paise=price,
            reorder_level_base=reorder,
        )
        for name, aliases, unit, base_unit, base_per_unit, price, reorder in ITEMS
    ]
    customers = [Customer(name=name, nicknames=nicknames) for name, nicknames in CUSTOMERS]
    suppliers = [Supplier(name=name, aliases=aliases) for name, aliases in SUPPLIERS]

    db.add_all(items + customers + suppliers)
    db.flush()
    return items, customers


def _open_stock(db, items: list[Item], rng: random.Random) -> None:
    """Start everyone comfortably stocked; sales then draw some down."""
    for item in items:
        opening = item.reorder_level_base * rng.choice([3, 4, 5])
        inventory.move(db, item, opening, "opening")


def _recent_sales(db, items: list[Item], customers: list[Customer], rng: random.Random) -> None:
    """Fourteen days of trade, so days-of-stock and the briefing have something to say."""
    today = date.today()

    for days_ago in range(14, 0, -1):
        when = now() - timedelta(days=days_ago)

        for _ in range(rng.randint(4, 9)):
            item = rng.choice(items)
            qty = item.base_per_unit * rng.choice([1, 1, 2]) if item.base_per_unit > 1 else rng.randint(1, 4)
            if inventory.on_hand(db, item.id) < qty:
                continue

            on_credit = rng.random() < 0.3
            customer = rng.choice(customers) if on_credit else None
            total = line_total_paise(item, qty)

            sale = Sale(
                customer_id=customer.id if customer else None,
                is_credit=on_credit,
                total_paise=total,
                created_at=when,
            )
            db.add(sale)
            db.flush()

            db.add(SaleLine(sale_id=sale.id, item_id=item.id, qty_base=qty, line_total_paise=total))
            movement = inventory.move(db, item, -qty, "sale", ref=f"sale:{sale.id}")
            movement.created_at = when

            if on_credit:
                ledger.add_credit(
                    db,
                    customer,
                    total,
                    due_date=today + timedelta(days=rng.choice([-2, 0, 0, 3, 7])),
                    sale_id=sale.id,
                )

    db.flush()


def seed(db, rng: random.Random | None = None) -> None:
    """Fill an empty database with a demo shop."""
    rng = rng or random.Random(7)
    items, customers = _create_catalog(db)
    _open_stock(db, items, rng)
    _recent_sales(db, items, customers, rng)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the demo shop")
    parser.add_argument("--reset", action="store_true", help="drop every table first")
    args = parser.parse_args()

    if args.reset:
        Base.metadata.drop_all(engine())
    Base.metadata.create_all(engine())

    with session() as db:
        if db.execute(select(Shop)).first():
            print("already seeded, nothing to do (use --reset to start over)")
            return
        seed(db)

    with session() as db:
        low = inventory.below_reorder_level(db)
        print(f"seeded {len(ITEMS)} items, {len(CUSTOMERS)} customers, {len(SUPPLIERS)} suppliers")
        print(f"outstanding credit: {ledger.outstanding_total(db) / 100:.2f}")
        print(f"items below reorder level: {', '.join(lv.item.name for lv in low) or 'none'}")


if __name__ == "__main__":
    main()
