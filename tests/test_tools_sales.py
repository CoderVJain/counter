"""record_sale and record_payment over a real MCP session.

The model is scripted, so these are offline and deterministic. Every figure asserted here was
computed by `domain/`, which is the point: the model only reports what it heard.
"""

import pytest

from counter.agent import llm
from counter.agent.parser import HeardLine, HeardSale
from counter.domain import inventory, ledger
from counter.domain.models import Customer, Item

pytestmark = pytest.mark.usefixtures("no_model")


@pytest.fixture
def stocked(shop):
    sugar = Item(
        name="sugar",
        aliases=["cheeni"],
        unit="kg",
        base_unit="g",
        base_per_unit=1000,
        price_paise=4500,
        reorder_level_base=2000,
    )
    sharma = Customer(name="Sharma ji", nicknames=["sharma"])
    shop.add_all([sugar, sharma])
    shop.flush()
    inventory.move(shop, sugar, 10_000, "opening")
    shop.commit()
    return shop


def _heard(monkeypatch, **kwargs):
    """Script what the model reports hearing, so the rest of the path is real."""
    sale = HeardSale(**kwargs)

    async def parse(*_args, **_kwargs):
        return sale

    monkeypatch.setattr(llm, "parse", parse)


async def test_a_cash_sale_is_written_and_leaves_the_shelf(connect, stocked, monkeypatch):
    _heard(monkeypatch, lines=[HeardLine(item="cheeni", qty="do", unit="kilo")])

    async with connect() as client:
        result = await client.call_tool(
            "record_sale", {"utterance": "do kilo cheeni", "idempotency_key": "k1"}
        )

    data = result.structured_content
    assert data["recorded"] is True
    assert data["lines"] == [{"item": "sugar", "quantity": "2 kg", "amount": "Rs 90"}]
    assert data["total"] == "Rs 90"
    assert data["on_credit"] is False
    assert inventory.on_hand(stocked, 1) == 8_000


async def test_a_credit_sale_owes_the_named_customer(connect, stocked, monkeypatch):
    _heard(
        monkeypatch,
        lines=[HeardLine(item="cheeni", qty="ek", unit="kilo")],
        customer="sharma",
        is_credit=True,
        due_spoken="kal",
    )

    async with connect() as client:
        result = await client.call_tool(
            "record_sale", {"utterance": "ek kilo cheeni sharma udhaar kal", "idempotency_key": "k2"}
        )

    data = result.structured_content
    assert data["customer"] == "Sharma ji"
    assert data["on_credit"] is True
    assert data["due"] == "tomorrow"
    assert ledger.balance(stocked, 1) == 4_500


async def test_saying_it_twice_does_not_sell_it_twice(connect, stocked, monkeypatch):
    """The whole reason a writing tool takes a key. Four kilos must not leave for one sentence."""
    _heard(monkeypatch, lines=[HeardLine(item="cheeni", qty="do", unit="kilo")])

    async with connect() as client:
        first = await client.call_tool(
            "record_sale", {"utterance": "do kilo cheeni", "idempotency_key": "same"}
        )
        second = await client.call_tool(
            "record_sale", {"utterance": "do kilo cheeni", "idempotency_key": "same"}
        )

    assert first.structured_content["already_recorded"] is False
    assert second.structured_content["already_recorded"] is True
    assert second.structured_content["sale_id"] == first.structured_content["sale_id"]
    assert inventory.on_hand(stocked, 1) == 8_000
    assert "Already recorded" in second.content[0].text


async def test_an_ambiguous_sentence_asks_instead_of_guessing(connect, stocked, monkeypatch):
    _heard(monkeypatch, lines=[HeardLine(item="oil", qty="ek", unit="litre")])

    async with connect() as client:
        result = await client.call_tool("record_sale", {"utterance": "ek litre oil", "idempotency_key": "k3"})

    assert not result.is_error
    assert result.structured_content["recorded"] is False
    assert result.structured_content["question"] == result.content[0].text
    assert "oil" in result.content[0].text


async def test_selling_more_than_is_there_is_refused_with_the_real_figure(connect, stocked, monkeypatch):
    _heard(monkeypatch, lines=[HeardLine(item="cheeni", qty="50", unit="kilo")])

    async with connect() as client:
        result = await client.call_tool(
            "record_sale", {"utterance": "50 kilo cheeni", "idempotency_key": "k4"}
        )

    assert result.is_error
    assert "only 10 kg sugar" in result.content[0].text
    assert inventory.on_hand(stocked, 1) == 10_000


async def test_a_refused_sale_leaves_its_key_free_to_retry(connect, stocked, monkeypatch):
    """A failed write must not burn the key, or the corrected sentence would be swallowed."""
    _heard(monkeypatch, lines=[HeardLine(item="cheeni", qty="50", unit="kilo")])

    async with connect() as client:
        assert (
            await client.call_tool("record_sale", {"utterance": "50 kilo", "idempotency_key": "retry"})
        ).is_error

        _heard(monkeypatch, lines=[HeardLine(item="cheeni", qty="do", unit="kilo")])
        good = await client.call_tool(
            "record_sale", {"utterance": "do kilo cheeni", "idempotency_key": "retry"}
        )

    assert good.structured_content["recorded"] is True
    assert inventory.on_hand(stocked, 1) == 8_000


async def test_a_payment_reduces_the_balance(connect, stocked):
    sharma = stocked.get(Customer, 1)
    ledger.add_credit(stocked, sharma, 50_000)
    stocked.commit()

    async with connect() as client:
        result = await client.call_tool(
            "record_payment", {"customer": "sharma", "amount_rupees": 200, "idempotency_key": "p1"}
        )

    assert result.structured_content["paid"] == "Rs 200"
    assert result.structured_content["balance"] == "Rs 300"
    assert ledger.balance(stocked, 1) == 30_000


async def test_a_repeated_payment_is_only_applied_once(connect, stocked):
    sharma = stocked.get(Customer, 1)
    ledger.add_credit(stocked, sharma, 50_000)
    stocked.commit()

    async with connect() as client:
        for _ in range(2):
            result = await client.call_tool(
                "record_payment", {"customer": "sharma", "amount_rupees": 200, "idempotency_key": "p2"}
            )

    assert result.structured_content["already_recorded"] is True
    assert ledger.balance(stocked, 1) == 30_000


async def test_paying_more_than_is_owed_is_refused(connect, stocked):
    sharma = stocked.get(Customer, 1)
    ledger.add_credit(stocked, sharma, 50_000)
    stocked.commit()

    async with connect() as client:
        result = await client.call_tool(
            "record_payment", {"customer": "sharma", "amount_rupees": 900, "idempotency_key": "p3"}
        )

    assert result.is_error
    assert "only owes Rs 500" in result.content[0].text
    assert ledger.balance(stocked, 1) == 50_000


async def test_an_unknown_customer_is_never_invented(connect, stocked):
    async with connect() as client:
        result = await client.call_tool(
            "record_payment", {"customer": "Verma ji", "amount_rupees": 100, "idempotency_key": "p4"}
        )

    assert result.is_error
    assert "Verma ji" in result.content[0].text
