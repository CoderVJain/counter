"""Stock math, the negative-stock guard, and days-of-stock."""

from datetime import timedelta

import pytest

from counter.domain import inventory
from counter.domain.models import Item, StockMovement, now


@pytest.fixture
def sugar(db):
    item = Item(
        name="sugar",
        aliases=["cheeni"],
        unit="kg",
        base_unit="g",
        base_per_unit=1000,
        price_paise=4500,
        reorder_level_base=2000,
    )
    db.add(item)
    db.flush()
    return item


def test_on_hand_folds_movements(db, sugar):
    inventory.move(db, sugar, 10_000, "opening")
    inventory.move(db, sugar, -2_500, "sale")
    assert inventory.on_hand(db, sugar.id) == 7_500


def test_on_hand_is_zero_with_no_movements(db, sugar):
    assert inventory.on_hand(db, sugar.id) == 0


def test_stock_cannot_go_negative(db, sugar):
    inventory.move(db, sugar, 1_000, "opening")

    with pytest.raises(inventory.InsufficientStock) as err:
        inventory.move(db, sugar, -1_500, "sale")

    assert err.value.have_base == 1_000
    assert err.value.wanted_base == 1_500
    assert inventory.on_hand(db, sugar.id) == 1_000  # nothing was written


def test_exact_stock_may_be_sold(db, sugar):
    inventory.move(db, sugar, 1_000, "opening")
    inventory.move(db, sugar, -1_000, "sale")
    assert inventory.on_hand(db, sugar.id) == 0


def test_days_of_stock_uses_sales_only(db, sugar):
    inventory.move(db, sugar, 14_000, "opening")
    for _ in range(7):
        inventory.move(db, sugar, -1_000, "sale")

    lv = inventory.level(db, sugar, window_days=14)
    assert lv.on_hand_base == 7_000
    assert lv.days_of_stock == 14.0  # 7000 on hand, 500/day


def test_days_of_stock_is_unknown_without_sales(db, sugar):
    inventory.move(db, sugar, 5_000, "opening")
    assert inventory.level(db, sugar).days_of_stock is None


def test_old_sales_fall_out_of_the_window(db, sugar):
    inventory.move(db, sugar, 10_000, "opening")
    stale = StockMovement(
        item_id=sugar.id,
        delta_base=-5_000,
        reason="sale",
        created_at=now() - timedelta(days=30),
    )
    db.add(stale)
    db.flush()

    assert inventory.daily_sales_rate(db, sugar.id, window_days=14) is None


def test_below_reorder_level_ranks_worst_first(db, sugar):
    maggi = Item(
        name="maggi",
        aliases=[],
        unit="packet",
        base_unit="piece",
        base_per_unit=1,
        price_paise=1400,
        reorder_level_base=20,
    )
    db.add(maggi)
    db.flush()

    inventory.move(db, sugar, 1_500, "opening")  # 500 under
    inventory.move(db, maggi, 19, "opening")  # 1 under

    low = inventory.below_reorder_level(db)
    assert [lv.item.name for lv in low] == ["sugar", "maggi"]
