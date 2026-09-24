"""A repeated voice command must never write twice."""

import pytest

from counter.domain import idempotency, inventory
from counter.domain.models import Item


@pytest.fixture
def sugar(db):
    item = Item(
        name="sugar",
        aliases=[],
        unit="kg",
        base_unit="g",
        base_per_unit=1000,
        price_paise=4500,
        reorder_level_base=0,
    )
    db.add(item)
    db.flush()
    return item


def test_work_runs_once_per_key(db):
    calls = []

    def work():
        calls.append(1)
        return {"sale_id": 7}

    first, replayed_first = idempotency.once(db, "utt-1", work)
    second, replayed_second = idempotency.once(db, "utt-1", work)

    assert calls == [1]
    assert first == second == {"sale_id": 7}
    assert replayed_first is False
    assert replayed_second is True


def test_a_repeated_sale_does_not_move_stock_twice(db, sugar):
    inventory.move(db, sugar, 10_000, "opening")

    def sell():
        inventory.move(db, sugar, -2_000, "sale", ref="utt-9")
        return {"sold_base": 2_000}

    idempotency.once(db, "utt-9", sell)
    idempotency.once(db, "utt-9", sell)

    assert inventory.on_hand(db, sugar.id) == 8_000


def test_different_keys_both_run(db):
    calls = []

    def work():
        calls.append(1)
        return {"n": len(calls)}

    idempotency.once(db, "utt-1", work)
    idempotency.once(db, "utt-2", work)

    assert calls == [1, 1]


def test_a_failed_write_leaves_the_key_free_to_retry(db, sugar):
    inventory.move(db, sugar, 1_000, "opening")
    db.commit()  # opening stock is already banked before the sale is attempted

    def sell_too_much():
        inventory.move(db, sugar, -5_000, "sale")
        return {}

    with pytest.raises(inventory.InsufficientStock):
        idempotency.once(db, "utt-3", sell_too_much)

    db.rollback()

    def sell_what_is_there():
        inventory.move(db, sugar, -1_000, "sale")
        return {"sold_base": 1_000}

    result, replayed = idempotency.once(db, "utt-3", sell_what_is_there)
    assert result == {"sold_base": 1_000}
    assert replayed is False
