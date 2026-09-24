"""Credit balances, payment application and dues."""

from datetime import date, timedelta

import pytest

from counter.domain import ledger
from counter.domain.models import Customer

TODAY = date(2026, 9, 24)


@pytest.fixture
def sharma(db):
    c = Customer(name="Sharma ji", nicknames=["sharma"])
    db.add(c)
    db.flush()
    return c


def test_balance_is_zero_for_a_new_customer(db, sharma):
    assert ledger.balance(db, sharma.id) == 0


def test_credit_then_payment_nets_out(db, sharma):
    ledger.add_credit(db, sharma, 50_000, due_date=TODAY)
    ledger.record_payment(db, sharma, 20_000)
    assert ledger.balance(db, sharma.id) == 30_000


def test_payment_cannot_exceed_balance(db, sharma):
    ledger.add_credit(db, sharma, 30_000, due_date=TODAY)

    with pytest.raises(ledger.Overpayment) as err:
        ledger.record_payment(db, sharma, 50_000)

    assert err.value.balance_paise == 30_000
    assert ledger.balance(db, sharma.id) == 30_000  # nothing was written


def test_paying_the_exact_balance_clears_it(db, sharma):
    ledger.add_credit(db, sharma, 30_000, due_date=TODAY)
    ledger.record_payment(db, sharma, 30_000)
    assert ledger.balance(db, sharma.id) == 0
    assert ledger.open_dues(db, sharma.id) == []


def test_payments_settle_the_oldest_due_first(db, sharma):
    ledger.add_credit(db, sharma, 10_000, due_date=TODAY)
    ledger.add_credit(db, sharma, 25_000, due_date=TODAY + timedelta(days=7))
    ledger.record_payment(db, sharma, 12_000)

    dues = ledger.open_dues(db, sharma.id)
    assert len(dues) == 1
    assert dues[0].remaining_paise == 23_000  # 10000 cleared, 2000 off the next
    assert dues[0].due_date == TODAY + timedelta(days=7)


def test_undated_credit_settles_last(db, sharma):
    ledger.add_credit(db, sharma, 5_000, due_date=None)
    ledger.add_credit(db, sharma, 5_000, due_date=TODAY)
    ledger.record_payment(db, sharma, 5_000)

    dues = ledger.open_dues(db, sharma.id)
    assert [d.due_date for d in dues] == [None]


def test_due_by_spans_customers_and_ignores_the_future(db, sharma):
    gupta = Customer(name="Gupta", nicknames=[])
    db.add(gupta)
    db.flush()

    ledger.add_credit(db, sharma, 10_000, due_date=TODAY - timedelta(days=2))  # overdue
    ledger.add_credit(db, gupta, 7_000, due_date=TODAY)  # due today
    ledger.add_credit(db, gupta, 9_000, due_date=TODAY + timedelta(days=5))  # later

    dues = ledger.due_by(db, TODAY)
    assert [d.entry.customer_id for d in dues] == [sharma.id, gupta.id]
    assert sum(d.remaining_paise for d in dues) == 17_000


def test_outstanding_total_sums_every_customer(db, sharma):
    gupta = Customer(name="Gupta", nicknames=[])
    db.add(gupta)
    db.flush()

    ledger.add_credit(db, sharma, 10_000, due_date=TODAY)
    ledger.add_credit(db, gupta, 15_000, due_date=TODAY)
    ledger.record_payment(db, sharma, 4_000)

    assert ledger.outstanding_total(db) == 21_000
