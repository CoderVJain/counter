"""Decide what to reorder first, and say why in a line a shopkeeper will act on.

The arithmetic is not here. `orders.suggest_reorder` already decides which items are below their
reorder level and how much to buy, from the movement log. This module does the two things code is
bad at: putting the list in the order a shopkeeper would care about, and explaining it in one
sentence.

Ranking is code as well, because "urgent" has a definition: days of stock left, soonest first, with
an item that has never sold treated as least urgent rather than most. A model ranking by vibe would
reorder the shop's cash into slow movers. The model only writes the sentence.
"""

from counter.agent import summarizer
from counter.domain.orders import Suggestion
from counter.domain.units import from_base

# An item with no sales history has no days-of-stock, so it sorts last rather than first.
NEVER_SOLD = float("inf")


def by_urgency(suggestions: list[Suggestion]) -> list[Suggestion]:
    """Soonest to run out first. Ties broken by name so the order never wobbles."""
    return sorted(
        suggestions,
        key=lambda s: (s.days_of_stock if s.days_of_stock is not None else NEVER_SOLD, s.item.name),
    )


def urgency_facts(suggestions: list[Suggestion], limit: int = 5) -> str:
    """The reorder list as plain facts, already ranked and already converted."""
    ranked = by_urgency(suggestions)[:limit]
    if not ranked:
        return "Nothing is below its reorder level."
    lines = []
    for s in ranked:
        left = from_base(s.item, s.on_hand_base)
        buy = from_base(s.item, s.qty_base)
        days = "no recent sales" if s.days_of_stock is None else f"{s.days_of_stock:.0f} days left"
        lines.append(f"{s.item.name}: {left} in stock, {days}, suggest buying {buy}")
    return "Low stock. " + ". ".join(lines) + "."


async def explain(suggestions: list[Suggestion], limit: int = 5) -> str:
    """One spoken sentence about what to reorder. Never invents a quantity."""
    return await summarizer.phrase(urgency_facts(suggestions, limit))
