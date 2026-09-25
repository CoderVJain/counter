"""Say back what happened, in a sentence a shopkeeper can hear over a noisy counter.

This is the only place a model writes text that a person will act on, which makes it the one place
a model could invent a number. It cannot here. Code assembles the facts, including every figure
already formatted, and the model is asked only to phrase them. Before the text is returned, every
number in it is checked against the numbers it was given: anything else and the sentence is thrown
away rather than spoken. A shopkeeper told the wrong balance stops trusting the whole till.

Keep the output short. This is heard, not read, and usually while someone is waiting for change.
"""

import re

from counter.agent import llm, prompts
from counter.agent.parser import ParsedSale
from counter.domain import dates
from counter.domain.units import from_base, rupees

SYSTEM = prompts.SPEAK

NUMBER = re.compile(r"\d+(?:\.\d+)?")


class NumberInvented(Exception):
    """The model spoke a figure it was not given. Carries both sides so the caller can fall back."""

    def __init__(self, said: str, allowed: set[str], text: str):
        self.said = said
        self.allowed = allowed
        self.text = text
        super().__init__(f"{said!r} is not among {sorted(allowed)}")


def _numbers(text: str) -> set[str]:
    """Every figure in a piece of text, normalised so 45.00 and 45 compare equal."""
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in NUMBER.findall(text)}


async def phrase(facts: str, *, smart: bool = False) -> str:
    """Put the facts into one spoken sentence, refusing any sentence that invents a figure."""
    text = await llm.complete(facts, system=SYSTEM, smart=smart)
    allowed = _numbers(facts)
    for said in _numbers(text):
        if said not in allowed:
            raise NumberInvented(said, allowed, text)
    return text


def sale_facts(sale: ParsedSale) -> str:
    """Everything worth saying about a recorded sale, with every figure computed in code."""
    lines = [f"{from_base(line.item, line.qty_base)} {line.item.name}" for line in sale.lines]
    facts = [f"Sold: {', '.join(lines)}.", f"Total: {rupees(sale.total_paise)}."]
    if sale.customer and sale.is_credit:
        facts.append(f"On credit for {sale.customer.name}.")
        if sale.due_date:
            facts.append(f"Due {dates.spoken(sale.due_date)}.")
    else:
        facts.append("Paid in cash.")
    return " ".join(facts)


async def say(facts: str, *, smart: bool = False) -> str:
    """Phrase the facts if a model is available, and fall back to the facts if anything stops it.

    The sentence is a nicety; the numbers are the product. A throttled provider, a gated account or
    an invented figure must not turn a correct answer into an error on a busy counter, so every
    failure degrades to the plain facts. The broad catch is deliberate: narrowing it would mean
    importing provider exception types here, and no module outside llm.py knows the provider.
    """
    try:
        return await phrase(facts, smart=smart)
    except Exception:
        return facts


async def sale_recorded(sale: ParsedSale) -> str:
    """Confirm a sale out loud. Never fails; the worst case is a flat sentence."""
    return await say(sale_facts(sale))
