"""Turn one spoken sentence into a sale the domain layer can write.

The split here is the whole point. The model does one job: report what it heard, word for word -
"cheeni", "dhai", "kilo", "Sharma ji". It does not choose a catalog row, convert a unit, or touch
money. Code does all three, against the database, in catalog.py and units.py. A model that is
merely transcribing cannot invent an item that does not exist, and cannot get a total wrong.

The catalog is deliberately NOT sent to the model. It costs nothing to leave out, it removes the
only place shop-controlled text could reach an instruction, and resolution is stricter in code
anyway. It also keeps the prompt free of a catalog version, so a repeated utterance caches cleanly.

Anything that cannot be resolved raises NeedsClarification carrying a speakable question. Guessing
is never an option: a wrong line on a ledger costs a shopkeeper real money and real trust.
"""

import re
from collections import Counter
from datetime import date

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from counter.agent import llm, prompts
from counter.domain import catalog, dates, units
from counter.domain.models import Customer, Item

SYSTEM = prompts.PARSE_SALE


class HeardLine(BaseModel):
    """One item and quantity heard in the sentence."""

    item: str = Field(description="The item as spoken, or its plain English name. Never a guess.")
    qty: str = Field(
        description=(
            "The quantity spoken immediately before the unit, copied exactly as said and never "
            'converted: "bees" stays "bees", "dhai" stays "dhai". Never multiply it by the unit: '
            '"ek dozen" is qty "ek" with unit "dozen", never qty "12".'
        )
    )
    unit: str | None = Field(
        default=None,
        description="Unit as spoken: kilo, gram, litre, ml, packet, piece, dozen. null if not said.",
    )


class HeardSale(BaseModel):
    """Everything heard in one spoken sale."""

    lines: list[HeardLine] = Field(description="One entry per item mentioned.")
    customer: str | None = Field(default=None, description="Person named, as spoken. null if none.")
    is_credit: bool = Field(default=False, description="True if taken on credit rather than paid now.")
    due_spoken: str | None = Field(default=None, description='When they will pay, as spoken: "Friday".')


class SaleLine:
    """A resolved line: a real item, a quantity in base units, and what it costs."""

    def __init__(self, item: Item, qty_base: int):
        self.item = item
        self.qty_base = qty_base
        self.total_paise = units.line_total_paise(item, qty_base)

    def __repr__(self) -> str:
        return f"SaleLine({self.item.name}, {self.qty_base}{self.item.base_unit}, {self.total_paise}p)"


class ParsedSale:
    """A sale that resolved cleanly. Every figure here was computed in code."""

    def __init__(
        self,
        lines: list[SaleLine],
        customer: Customer | None,
        is_credit: bool,
        due_spoken: str | None,
        due_date: date | None,
    ):
        self.lines = lines
        self.customer = customer
        self.is_credit = is_credit
        self.due_spoken = due_spoken
        self.due_date = due_date
        self.total_paise = sum(line.total_paise for line in lines)


class NeedsClarification(Exception):
    """Raised instead of guessing. Carries a question the assistant can speak aloud."""

    def __init__(self, question: str, options: list[str] | None = None):
        self.question = question
        self.options = options or []
        super().__init__(question)


class NothingHeard(Exception):
    """The sentence named no items at all, so there is nothing to record."""


def _resolve_line(db: Session, heard: HeardLine) -> SaleLine:
    """One heard line onto a real item and a base quantity, or a question."""
    try:
        item = catalog.find_item(db, heard.item)
    except catalog.AmbiguousItem as exc:
        names = [i.name for i in exc.candidates]
        raise NeedsClarification(f"Did you mean {' or '.join(names)}?", names) from exc
    except catalog.UnknownItem as exc:
        raise NeedsClarification(f"I do not stock anything called {heard.item}. What is it?") from exc

    try:
        qty_base = units.to_base(item, heard.qty, heard.unit)
    except units.UnknownUnit as exc:
        raise NeedsClarification(f"How much {item.name}? I did not catch the amount.") from exc
    except units.UnitMismatch as exc:
        raise NeedsClarification(f"{item.name} is not sold by {heard.unit}. How much?") from exc

    if qty_base <= 0:
        raise NeedsClarification(f"How much {item.name} should I record?")
    return SaleLine(item, qty_base)


def _resolve_customer(db: Session, spoken: str | None) -> Customer | None:
    """The named customer, or None for a cash sale."""
    if not spoken:
        return None
    try:
        return catalog.find_customer(db, spoken)
    except catalog.AmbiguousCustomer as exc:
        names = [c.name for c in exc.candidates]
        raise NeedsClarification(f"Which one, {' or '.join(names)}?", names) from exc
    except catalog.UnknownCustomer as exc:
        raise NeedsClarification(f"I do not have {spoken} on the books. Add them?") from exc


def _resolve_due(spoken: str | None) -> date | None:
    """The day they promised to pay, or None if no day was named."""
    if not spoken:
        return None
    try:
        return dates.to_date(spoken)
    except dates.UnknownDate as exc:
        raise NeedsClarification(f"When will they pay? I did not catch {spoken}.") from exc


def resolve(db: Session, heard: HeardSale) -> ParsedSale:
    """Turn what was heard into real rows and real money. No model involved."""
    if not heard.lines:
        raise NothingHeard("no items in the sentence")
    lines = [_resolve_line(db, line) for line in heard.lines]
    customer = _resolve_customer(db, heard.customer)

    # Naming a payment day is a credit sale whatever the model ticked. Deriving it here rather than
    # trusting the flag is the difference between a logged debt and money quietly written off.
    is_credit = heard.is_credit or bool(heard.due_spoken)
    if is_credit and customer is None:
        raise NeedsClarification("Who is taking this on credit?")
    return ParsedSale(lines, customer, is_credit, heard.due_spoken, _resolve_due(heard.due_spoken))


# The same sentence costs the same tokens every time it is said, and a counter repeats itself all
# day. Only what the model HEARD is cached; resolution re-runs against the live database, so a
# price change or a new item is picked up immediately. The catalog never reaches the prompt, so
# there is no catalog version to key on.
MAX_CACHED = 256
_heard_cache: dict[str, HeardSale] = {}


async def _hear(utterance: str) -> HeardSale:
    """What the model made of the sentence, remembered so a repeat costs nothing."""
    key = " ".join(utterance.lower().split())
    if key in _heard_cache:
        return _heard_cache[key]
    heard = await llm.parse(utterance, HeardSale, system=SYSTEM)
    if len(_heard_cache) >= MAX_CACHED:
        del _heard_cache[next(iter(_heard_cache))]
    _heard_cache[key] = heard
    return heard


SPOKEN_WORD = re.compile(r"[a-z]+|\d+(?:\.\d+)?")


def _spoken_tokens(utterance: str) -> Counter[str]:
    """How many times the sentence says each word or number, lowercased. "2kg" yields 2 and kg."""
    return Counter(SPOKEN_WORD.findall(utterance.lower()))


def check_quantities(utterance: str, heard: HeardSale) -> None:
    """Refuse a quantity the sentence does not contain, rather than writing it.

    The model is asked only to copy the quantity it heard, and measured on 25 Sep with Nova Micro at
    temperature zero it sometimes does not: "do kilo cheeni cash" came back as qty "bees" (twenty)
    and "do kilo cheeni Sharma ji ko, kal dega" as qty "ek" (one). Both are real words that resolve
    cleanly, so both would have been written, and Nova Lite was no better on the same sentences.

    A wrong quantity is the most expensive mistake this system can make: it is silent, it is on a
    ledger, and the shopkeeper finds out when the stock does not match. The sentence is right here in
    code, so the claim is checked instead of trusted. Anything nobody said becomes a question, which
    costs one more turn and never costs money.

    Counting matters, not just presence. The 25 Sep eval had "do doodh aur ek bread" come back with
    qty "ek" on both lines: the milk was recorded as one litre instead of two, and "ek" is in the
    sentence, so looking it up would have passed it. Each line therefore uses up one occurrence of
    its own word, and the second claim on a word said once is a question.
    """
    unclaimed = _spoken_tokens(utterance)
    for line in heard.lines:
        said = line.qty.strip().lower()
        if not said:
            continue
        if not unclaimed[said]:
            raise NeedsClarification(f"How much {line.item}? I did not catch the amount.")
        unclaimed[said] -= 1


def _spoken_units(utterance: str) -> set[str]:
    """The units the sentence actually names, in canonical form."""
    found = set()
    for token in SPOKEN_WORD.findall(utterance.lower()):
        try:
            found.add(units.canonical_unit(token))
        except units.UnknownUnit:
            continue
    return found


def drop_unspoken_units(utterance: str, heard: HeardSale) -> HeardSale:
    """Ignore a unit nobody said, so an invented one cannot multiply an order.

    The 25 Sep eval had "Verma bhai ko das anda" come back with unit "dozen", which turned ten eggs
    into a hundred and twenty. No unit was spoken at all, and when none is spoken the item's own
    selling unit is exactly what the shopkeeper means, so the claim is dropped rather than trusted.

    A unit that is spoken in another form is kept: "500 g" and unit "gram" agree once both are
    canonical. A word the shop does not use at all is left alone, so it still reaches the question
    that `_resolve_line` asks about it. The copy is deliberate - the original is in the parse cache.
    """
    spoken = _spoken_units(utterance)
    fixed = heard.model_copy(deep=True)
    for line in fixed.lines:
        if not line.unit:
            continue
        try:
            canonical = units.canonical_unit(line.unit)
        except units.UnknownUnit:
            continue
        if canonical not in spoken:
            line.unit = None
    return fixed


async def parse_sale(db: Session, utterance: str) -> ParsedSale:
    """Listen to one sentence and return a sale ready to write, or ask a question."""
    heard = await _hear(utterance)
    check_quantities(utterance, heard)
    return resolve(db, drop_unspoken_units(utterance, heard))
