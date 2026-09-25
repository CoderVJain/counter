"""A sale writes the rows, takes the stock, and books the debt - or none of those things."""

from datetime import date

import pytest
from sqlalchemy import select

from counter.domain import inventory, ledger, sales
from counter.domain.models import Customer, Item, Sale, SaleLine, StockMovement


@pytest.fixture
def shop(db):
    sugar = Item(name="sugar", aliases=[], unit="kg", base_unit="g", base_per_unit=1000, price_paise=4500)
    bread = Item(
        name="bread", aliases=[], unit="packet", base_unit="piece", base_per_unit=1, price_paise=4500
    )
    sharma = Customer(name="Sharma ji", nicknames=[])
    db.add_all([sugar, bread, sharma])
    db.flush()
    inventory.move(db, sugar, 10_000, "opening")
    inventory.move(db, bread, 20, "opening")
    db.commit()
    return db, sugar, bread, sharma


def test_a_cash_sale_writes_lines_and_totals_them(shop):
    db, sugar, bread, _ = shop
    sale = sales.record(db, [(sugar, 2000), (bread, 3)])
    assert sale.total_paise == 9000 + 13500
    assert db.execute(select(SaleLine)).scalars().all().__len__() == 2
    assert sale.is_credit is False


def test_the_stock_actually_leaves_the_shelf(shop):
    db, sugar, _, _ = shop
    before = inventory.on_hand(db, sugar.id)
    sales.record(db, [(sugar, 2500)])
    assert inventory.on_hand(db, sugar.id) == before - 2500


def test_each_movement_points_back_at_its_sale(shop):
    db, sugar, _, _ = shop
    sale = sales.record(db, [(sugar, 1000)])
    refs = [m.ref for m in db.execute(select(StockMovement)).scalars() if m.ref]
    assert f"sale:{sale.id}" in refs


def test_a_credit_sale_books_what_is_owed(shop):
    db, sugar, _, sharma = shop
    sale = sales.record(db, [(sugar, 2000)], customer=sharma, is_credit=True, due_date=date(2026, 10, 2))
    assert ledger.balance(db, sharma.id) == sale.total_paise
    assert ledger.open_dues(db, sharma.id)[0].due_date == date(2026, 10, 2)


def test_a_cash_sale_owes_nothing(shop):
    db, sugar, _, sharma = shop
    sales.record(db, [(sugar, 2000)])
    assert ledger.balance(db, sharma.id) == 0


def test_the_price_comes_from_the_shelf_not_the_caller(shop):
    """Two kilos of sugar is Rs 90 because the item says so, whatever anyone else thinks."""
    db, sugar, _, _ = shop
    assert sales.record(db, [(sugar, 2000)]).total_paise == 9000


def test_selling_more_than_is_there_is_refused(shop):
    db, sugar, _, _ = shop
    with pytest.raises(inventory.InsufficientStock):
        sales.record(db, [(sugar, 50_000)])


def test_a_refused_line_undoes_the_whole_sale(shop):
    """The first item must not leave the shelf when the second one cannot be met."""
    db, sugar, bread, _ = shop
    sugar_before = inventory.on_hand(db, sugar.id)
    with pytest.raises(inventory.InsufficientStock):
        sales.record(db, [(sugar, 1000), (bread, 999)])
    db.rollback()
    assert inventory.on_hand(db, sugar.id) == sugar_before
    assert db.execute(select(Sale)).scalars().all() == []


def test_an_empty_sale_is_refused(shop):
    db, *_ = shop
    with pytest.raises(sales.NothingToSell):
        sales.record(db, [])


def test_credit_with_nobody_to_owe_it_is_refused(shop):
    db, sugar, _, _ = shop
    with pytest.raises(sales.CreditWithoutCustomer):
        sales.record(db, [(sugar, 1000)], is_credit=True)
