"""Short spoken text, with every figure traceable to something code computed."""

import pytest

from counter.agent import parser, summarizer
from counter.agent.parser import HeardLine, HeardSale
from counter.domain import dates
from counter.domain.models import Customer, Item


@pytest.fixture
def sale(db):
    db.add_all(
        [
            Item(
                name="sugar",
                aliases=["cheeni"],
                unit="kg",
                base_unit="g",
                base_per_unit=1000,
                price_paise=4500,
            ),
            Customer(name="Sharma ji", nicknames=["sharmaji"]),
        ]
    )
    db.commit()
    heard = HeardSale(
        lines=[HeardLine(item="cheeni", qty="2", unit="kilo")],
        customer="sharmaji",
        is_credit=True,
        due_spoken="kal",
    )
    return parser.resolve(db, heard)


def test_the_facts_carry_every_figure_already_formatted(sale):
    facts = summarizer.sale_facts(sale)
    assert "2 kg sugar" in facts
    assert "Rs 90" in facts
    assert "Sharma ji" in facts
    assert "tomorrow" in facts


def test_a_cash_sale_says_so(db):
    db.add(
        Item(name="bread", aliases=[], unit="packet", base_unit="piece", base_per_unit=1, price_paise=4500)
    )
    db.commit()
    heard = HeardSale(lines=[HeardLine(item="bread", qty="1")])
    assert "cash" in summarizer.sale_facts(parser.resolve(db, heard)).lower()


async def test_a_sentence_that_invents_a_figure_is_refused(monkeypatch):
    """The model saying Rs 250 when code said Rs 90 must never reach the shopkeeper."""

    async def inflate(prompt, *, system=None, smart=False):
        return "Sold 2 kg sugar for Rs 250 on credit."

    monkeypatch.setattr(summarizer.llm, "complete", inflate)
    with pytest.raises(summarizer.NumberInvented) as caught:
        await summarizer.phrase("Sold: 2 kg sugar. Total: Rs 90.")
    assert caught.value.said == "250"


async def test_a_faithful_sentence_passes(monkeypatch):
    async def faithful(prompt, *, system=None, smart=False):
        return "Noted, 2 kg sugar for Rs 90 on Sharma ji's account."

    monkeypatch.setattr(summarizer.llm, "complete", faithful)
    said = await summarizer.phrase("Sold: 2 kg sugar. Total: Rs 90. On credit for Sharma ji.")
    assert "Rs 90" in said


async def test_trailing_zeros_do_not_count_as_a_new_figure(monkeypatch):
    """Rs 112.50 said back as Rs 112.5 is the same money, not an invention."""

    async def restyled(prompt, *, system=None, smart=False):
        return "That is Rs 112.5 please."

    monkeypatch.setattr(summarizer.llm, "complete", restyled)
    assert await summarizer.phrase("Total: Rs 112.50.")


async def test_an_embellished_sentence_falls_back_to_the_plain_facts(sale, monkeypatch):
    """Better a flat sentence than a wrong number spoken aloud."""

    async def inflate(prompt, *, system=None, smart=False):
        return "Sure! That comes to Rs 9999."

    monkeypatch.setattr(summarizer.llm, "complete", inflate)
    said = await summarizer.sale_recorded(sale)
    assert said == summarizer.sale_facts(sale)
    assert "Rs 90" in said


def test_dates_are_spoken_not_printed(sale):
    assert str(dates.today()) not in summarizer.sale_facts(sale)


async def test_a_dead_provider_still_returns_the_facts(sale, monkeypatch):
    """A throttle or a gated account must not turn a correct sale into an error on a busy counter."""

    async def down(prompt, *, system=None, smart=False):
        raise RuntimeError("429 rate limit")

    monkeypatch.setattr(summarizer.llm, "complete", down)
    said = await summarizer.sale_recorded(sale)
    assert "Rs 90" in said
    assert "Sharma ji" in said
