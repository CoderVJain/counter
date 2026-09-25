"""get_dues over a real MCP session: one customer's book, or everything due today."""

from datetime import timedelta

import pytest

from counter.domain import dates, ledger
from counter.domain.models import Customer

pytestmark = pytest.mark.usefixtures("no_model")


@pytest.fixture
def books(shop):
    """Sharma ji owes for today and next week; Gupta is late; Verma ji owes nothing."""
    today = dates.today()
    sharma = Customer(name="Sharma ji", nicknames=["sharma"])
    gupta = Customer(name="Gupta", nicknames=[])
    verma = Customer(name="Verma ji", nicknames=[])
    shop.add_all([sharma, gupta, verma])
    shop.flush()
    ledger.add_credit(shop, sharma, 20_000, due_date=today)
    ledger.add_credit(shop, sharma, 30_000, due_date=today + timedelta(days=7))
    ledger.add_credit(shop, gupta, 10_000, due_date=today - timedelta(days=3))
    shop.commit()
    return shop


async def test_one_customer_hears_their_whole_book(connect, books):
    async with connect() as client:
        result = await client.call_tool("get_dues", {"customer": "sharma"})

    data = result.structured_content
    assert data["total"] == "Rs 500"
    assert [line["due"] for line in data["lines"]] == [
        "today",
        dates.spoken(dates.today() + timedelta(days=7)),
    ]
    assert "Sharma ji owes Rs 500, Rs 200 due today." == result.content[0].text


async def test_no_customer_hears_only_what_is_due_today_or_late(connect, books):
    async with connect() as client:
        result = await client.call_tool("get_dues", {})

    data = result.structured_content
    assert data["total"] == "Rs 300"
    assert [line["customer"] for line in data["lines"]] == ["Gupta", "Sharma ji"]
    assert data["lines"][0]["overdue"] is True
    assert data["lines"][1]["overdue"] is False


async def test_a_customer_who_owes_nothing_is_said_so(connect, books):
    async with connect() as client:
        result = await client.call_tool("get_dues", {"customer": "Verma ji"})

    assert result.structured_content["lines"] == []
    assert result.content[0].text == "Verma ji owes nothing."


async def test_a_settled_charge_stops_being_due(connect, books):
    sharma = books.get(Customer, 1)
    ledger.record_payment(books, sharma, 20_000)
    books.commit()

    async with connect() as client:
        result = await client.call_tool("get_dues", {"customer": "sharma"})

    assert result.structured_content["total"] == "Rs 300"
    assert [line["due"] for line in result.structured_content["lines"]] == [
        dates.spoken(dates.today() + timedelta(days=7))
    ]


async def test_an_unknown_customer_is_never_invented(connect, books):
    async with connect() as client:
        result = await client.call_tool("get_dues", {"customer": "Khanna"})

    assert result.is_error
    assert "Khanna" in result.content[0].text
