"""Reorder suggestions ranked by how soon the shelf empties, explained without new numbers."""

import pytest

from counter.agent import forecaster, summarizer
from counter.domain.models import Item
from counter.domain.orders import Suggestion


def suggestion(name: str, days, on_hand=1000, qty=2000) -> Suggestion:
    item = Item(
        name=name,
        aliases=[],
        unit="kg",
        base_unit="g",
        base_per_unit=1000,
        price_paise=4500,
        reorder_level_base=1000,
    )
    return Suggestion(item=item, qty_base=qty, on_hand_base=on_hand, days_of_stock=days)


def test_the_soonest_to_run_out_comes_first():
    ranked = forecaster.by_urgency([suggestion("rice", 9), suggestion("sugar", 2), suggestion("dal", 5)])
    assert [s.item.name for s in ranked] == ["sugar", "dal", "rice"]


def test_an_item_that_never_sells_is_least_urgent_not_most():
    """days_of_stock is None for no sales history. Sorting that first would buy the wrong stock."""
    ranked = forecaster.by_urgency([suggestion("candles", None), suggestion("sugar", 3)])
    assert [s.item.name for s in ranked] == ["sugar", "candles"]


def test_ties_are_broken_by_name_so_the_order_never_wobbles():
    ranked = forecaster.by_urgency([suggestion("rice", 4), suggestion("dal", 4)])
    assert [s.item.name for s in ranked] == ["dal", "rice"]


def test_the_facts_are_already_converted_out_of_base_units():
    facts = forecaster.urgency_facts([suggestion("sugar", 2, on_hand=1500, qty=2500)])
    assert "1.5 kg in stock" in facts
    assert "suggest buying 2.5 kg" in facts


def test_an_empty_list_says_nothing_is_low():
    assert "Nothing is below" in forecaster.urgency_facts([])


def test_only_the_top_few_are_spoken():
    many = [suggestion(f"item{i}", i) for i in range(10)]
    assert forecaster.urgency_facts(many, limit=3).count(" in stock") == 3


async def test_an_explanation_that_invents_a_quantity_is_refused(monkeypatch):
    async def inflate(prompt, *, system=None, smart=False):
        return "Buy 99 kg of sugar today."

    monkeypatch.setattr(summarizer.llm, "complete", inflate)
    with pytest.raises(summarizer.NumberInvented):
        await forecaster.explain([suggestion("sugar", 2)])
