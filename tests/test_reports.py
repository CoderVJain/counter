"""A day's figures, counted in shop time rather than UTC."""

from datetime import date, datetime, timedelta

import pytest

from counter.domain import inventory, reports, sales
from counter.domain.dates import SHOP_TZ
from counter.domain.models import Customer, Item

DAY = date(2026, 9, 25)


@pytest.fixture
def shop(db):
    sugar = Item(name="sugar", aliases=[], unit="kg", base_unit="g", base_per_unit=1000, price_paise=4500)
    bread = Item(
        name="bread", aliases=[], unit="packet", base_unit="piece", base_per_unit=1, price_paise=4500
    )
    sharma = Customer(name="Sharma ji", nicknames=[])
    db.add_all([sugar, bread, sharma])
    db.flush()
    inventory.move(db, sugar, 50_000, "opening")
    inventory.move(db, bread, 100, "opening")
    db.commit()
    return db, sugar, bread, sharma


def at(db, when: datetime, sale):
    """Move a sale to a chosen moment, since the default is now."""
    sale.created_at = when
    db.flush()


def test_a_quiet_day_counts_nothing(shop):
    db, *_ = shop
    summary = reports.for_day(db, DAY)
    assert summary.sale_count == 0
    assert summary.takings_paise == 0
    assert summary.top_sellers == []


def test_takings_add_up_across_sales(shop):
    db, sugar, bread, _ = shop
    noon = datetime.combine(DAY, datetime.min.time(), tzinfo=SHOP_TZ) + timedelta(hours=12)
    at(db, noon, sales.record(db, [(sugar, 2000)]))
    at(db, noon, sales.record(db, [(bread, 2)]))
    summary = reports.for_day(db, DAY)
    assert summary.sale_count == 2
    assert summary.takings_paise == 9000 + 9000


def test_credit_is_counted_separately_from_the_total(shop):
    db, sugar, _, sharma = shop
    noon = datetime.combine(DAY, datetime.min.time(), tzinfo=SHOP_TZ) + timedelta(hours=12)
    at(db, noon, sales.record(db, [(sugar, 2000)]))
    at(db, noon, sales.record(db, [(sugar, 1000)], customer=sharma, is_credit=True))
    summary = reports.for_day(db, DAY)
    assert summary.takings_paise == 9000 + 4500
    assert summary.credit_given_paise == 4500
    assert summary.outstanding_paise == 4500


def test_best_earner_comes_first(shop):
    db, sugar, bread, _ = shop
    noon = datetime.combine(DAY, datetime.min.time(), tzinfo=SHOP_TZ) + timedelta(hours=12)
    at(db, noon, sales.record(db, [(bread, 1)]))  # Rs 45
    at(db, noon, sales.record(db, [(sugar, 4000)]))  # Rs 180
    top = reports.for_day(db, DAY).top_sellers
    assert [s.item.name for s in top] == ["sugar", "bread"]
    assert top[0].total_paise == 18000
    assert top[0].qty_base == 4000


def test_the_same_item_sold_twice_is_one_row(shop):
    db, sugar, _, _ = shop
    noon = datetime.combine(DAY, datetime.min.time(), tzinfo=SHOP_TZ) + timedelta(hours=12)
    at(db, noon, sales.record(db, [(sugar, 1000)]))
    at(db, noon, sales.record(db, [(sugar, 2000)]))
    top = reports.for_day(db, DAY).top_sellers
    assert len(top) == 1
    assert top[0].qty_base == 3000


def test_a_late_evening_sale_belongs_to_that_day_not_the_next(shop):
    """Half past eleven at night in India is already tomorrow in UTC. It is still today's takings."""
    db, sugar, _, _ = shop
    late = datetime.combine(DAY, datetime.min.time(), tzinfo=SHOP_TZ) + timedelta(hours=23, minutes=30)
    at(db, late, sales.record(db, [(sugar, 1000)]))
    assert reports.takings(db, DAY) == 4500
    assert reports.takings(db, DAY + timedelta(days=1)) == 0


def test_a_sale_just_after_midnight_belongs_to_the_new_day(shop):
    db, sugar, _, _ = shop
    just_after = datetime.combine(DAY, datetime.min.time(), tzinfo=SHOP_TZ) + timedelta(days=1, minutes=5)
    at(db, just_after, sales.record(db, [(sugar, 1000)]))
    assert reports.takings(db, DAY) == 0
    assert reports.takings(db, DAY + timedelta(days=1)) == 4500
