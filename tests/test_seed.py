"""The demo shop seeds into a usable state."""

import random

from sqlalchemy import delete

from counter.domain import inventory, ledger, orders
from counter.domain.models import Base, Customer, Item, Sale, Supplier
from counter.seed import seed


def test_seed_builds_a_shop_that_can_be_demoed(db):
    seed(db, random.Random(7))

    assert db.query(Item).count() == 40
    assert db.query(Customer).count() == 10
    assert db.query(Supplier).count() == 2
    assert db.query(Sale).count() > 0

    # Every item ended up with a sane, non-negative stock level.
    for item in db.query(Item).all():
        assert inventory.on_hand(db, item.id) >= 0

    # There is credit on the books and something worth reordering, so the
    # briefing and dues flows have real data behind them.
    assert ledger.outstanding_total(db) > 0
    assert orders.suggest_reorder(db) != []


def test_seed_is_deterministic(db):
    """Same seed, same shop, so the demo shows identical numbers on every run."""
    seed(db, random.Random(7))
    first = {i.name: inventory.on_hand(db, i.id) for i in db.query(Item).all()}

    for table in reversed(Base.metadata.sorted_tables):
        db.execute(delete(table))
    db.flush()

    seed(db, random.Random(7))
    second = {i.name: inventory.on_hand(db, i.id) for i in db.query(Item).all()}

    assert first == second


def test_aliases_cover_the_hinglish_a_shopkeeper_says(db):
    seed(db, random.Random(7))
    aliases = {a for item in db.query(Item).all() for a in item.aliases}

    for spoken in ("cheeni", "atta", "doodh", "namak", "chai", "dal"):
        assert spoken in aliases
