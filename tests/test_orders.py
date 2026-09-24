"""Supplier orders are two-step and cannot skip or repeat a step."""

import pytest

from counter.domain import inventory, orders
from counter.domain.models import Item, Supplier


@pytest.fixture
def gupta(db):
    s = Supplier(name="Gupta Traders", aliases=["gupta"])
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def parle(db):
    item = Item(
        name="parle-g",
        aliases=["parle", "biscuit"],
        unit="packet",
        base_unit="piece",
        base_per_unit=1,
        price_paise=1000,
        reorder_level_base=20,
    )
    db.add(item)
    db.flush()
    return item


def test_draft_holds_its_lines(db, gupta, parle):
    order = orders.create_draft(db, gupta, [(parle, 50)])
    assert order.status == orders.DRAFT
    assert [(ln.item_id, ln.qty_base) for ln in order.lines] == [(parle.id, 50)]


def test_an_empty_order_is_refused(db, gupta):
    with pytest.raises(orders.EmptyOrder):
        orders.create_draft(db, gupta, [])


def test_confirming_a_draft_moves_it_forward(db, gupta, parle):
    order = orders.create_draft(db, gupta, [(parle, 50)])
    assert orders.confirm(db, order.id).status == orders.CONFIRMED


def test_a_draft_cannot_be_confirmed_twice(db, gupta, parle):
    order = orders.create_draft(db, gupta, [(parle, 50)])
    orders.confirm(db, order.id)

    with pytest.raises(orders.InvalidTransition):
        orders.confirm(db, order.id)


def test_sending_requires_confirmation_first(db, gupta, parle):
    order = orders.create_draft(db, gupta, [(parle, 50)])

    with pytest.raises(orders.InvalidTransition):
        orders.mark_sent(db, order.id)

    orders.confirm(db, order.id)
    assert orders.mark_sent(db, order.id).status == orders.SENT


def test_an_unknown_order_id_is_named_as_such(db):
    with pytest.raises(orders.UnknownOrder):
        orders.confirm(db, 999)


def test_confirming_does_not_move_stock(db, gupta, parle):
    inventory.move(db, parle, 5, "opening")
    order = orders.create_draft(db, gupta, [(parle, 50)])
    orders.confirm(db, order.id)

    assert inventory.on_hand(db, parle.id) == 5  # ordered is not arrived


def test_suggestions_top_up_to_twice_the_reorder_level(db, parle):
    inventory.move(db, parle, 5, "opening")  # reorder level is 20

    suggestions = orders.suggest_reorder(db)
    assert len(suggestions) == 1
    assert suggestions[0].item.name == "parle-g"
    assert suggestions[0].qty_base == 35  # up to 40 from 5


def test_well_stocked_items_are_not_suggested(db, parle):
    inventory.move(db, parle, 100, "opening")
    assert orders.suggest_reorder(db) == []


def test_drafts_lists_only_open_drafts(db, gupta, parle):
    first = orders.create_draft(db, gupta, [(parle, 10)])
    orders.create_draft(db, gupta, [(parle, 20)])
    orders.confirm(db, first.id)

    assert [o.id for o in orders.drafts(db)] == [first.id + 1]
