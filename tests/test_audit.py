"""Every write leaves one traceable line, and no line carries a sentence or a name."""

import pytest

from counter.domain import audit, inventory, ledger, orders, sales
from counter.domain.models import Customer, Item, Supplier


@pytest.fixture
def shop(db):
    sugar = Item(
        name="sugar",
        aliases=["cheeni"],
        unit="kg",
        base_unit="g",
        base_per_unit=1000,
        price_paise=4500,
        reorder_level_base=2000,
    )
    db.add_all([sugar, Customer(name="Sharma ji", nicknames=[]), Supplier(name="Gupta", aliases=[])])
    db.flush()
    inventory.move(db, sugar, 10_000, "opening")
    return db


def test_a_sale_is_recorded_in_the_trail(shop):
    sugar = shop.get(Item, 1)
    sale = sales.record(shop, [(sugar, 2_000)])

    line = audit.trail(shop)[0]
    assert line.action == audit.SALE
    assert line.detail["sale_id"] == sale.id
    assert line.detail["total_paise"] == 9_000


def test_a_payment_records_what_is_left(shop):
    sharma = shop.get(Customer, 1)
    ledger.add_credit(shop, sharma, 50_000)
    ledger.record_payment(shop, sharma, 20_000)

    line = audit.trail(shop)[0]
    assert line.action == audit.PAYMENT
    assert line.detail == {"customer_id": sharma.id, "paid_paise": 20_000, "balance_paise": 30_000}


def test_confirming_and_sending_an_order_are_separate_lines(shop):
    sugar = shop.get(Item, 1)
    supplier = shop.get(Supplier, 1)
    order = orders.create_draft(shop, supplier, [(sugar, 5_000)])
    orders.confirm(shop, order.id)
    orders.mark_sent(shop, order.id)

    actions = [line.action for line in audit.trail(shop)]
    assert actions[:2] == [audit.ORDER_SENT, audit.ORDER_CONFIRMED]


def test_the_trail_holds_no_sentence_and_no_name(shop):
    """Identifiers and amounts only. A voice log full of customer names is a liability."""
    sugar = shop.get(Item, 1)
    sharma = shop.get(Customer, 1)
    sales.record(shop, [(sugar, 1_000)], customer=sharma, is_credit=True)

    line = audit.trail(shop)[0]
    assert line.utterance is None
    assert "Sharma ji" not in str(line.detail)
    assert line.detail["customer_id"] == sharma.id


def test_a_kept_sentence_is_capped(shop):
    audit.record(shop, audit.SALE, {}, utterance="x" * 900)
    assert len(audit.trail(shop)[0].utterance) == audit.MAX_UTTERANCE


def test_a_refused_sale_leaves_no_trail(shop):
    """The audit line rolls back with the write, so it can never describe something that did not happen."""
    sugar = shop.get(Item, 1)
    with pytest.raises(inventory.InsufficientStock):
        sales.record(shop, [(sugar, 50_000)])
    shop.rollback()

    assert audit.trail(shop) == []
