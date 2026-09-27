"""Which tool the sentence means. The one model call this host makes.

A real Alexa+ does this part itself: it reads the tool descriptions the add-on publishes and picks
one. We have to stand in for it, so this module does the same job from the same material - the
descriptions arrive from `tools/list` and nothing about the shop is hard-coded here. Trimming those
descriptions to save tokens would make the choice easier than the real one, so they are sent whole.

Three rules hold this to the same line the rest of the project takes.

**The model chooses; it does not act.** A name that is not in the listed set is refused rather than
called, and the arguments are assembled here in `arguments()` from a few spoken fields. In
particular an **idempotency key is never taken from the model** - the host makes one per request, so
a retried request is one sale and a sentence said twice is two.

**The utterance is data.** It goes through `prompts.as_data` into the user turn, while the
instruction and the tool list go in the system prompt, which is also why the catalog does not count
against `llm.MAX_PROMPT_CHARS`: that cap guards the user turn, where outside text arrives.

**A repeat is free.** A counter says the same thing all day, and every call is billed, so the choice
is cached on the normalised sentence exactly as `parser._heard_cache` caches a parse.

Logs carry tool names and nothing else - no utterance, no customer, no amount.
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

from counter.agent import llm, prompts
from sim_client.host import Tool

log = logging.getLogger(__name__)

CHOOSE = (
    "You route a small Indian shopkeeper's spoken sentence to exactly one tool of a shop's back "
    "office. The speech mixes Hindi and English. Choose the single tool whose description best "
    "fits what was said, and fill only the fields that tool needs.\n"
    "Copy names, items and days exactly as spoken, honorifics included. Never invent a value: if "
    "the sentence does not say it, leave the field out.\n"
    "Anything that records goods leaving the shop is a sale, whether it was paid for or taken on "
    "credit. Money coming in from a named person is a payment.\n"
    "Tools, as name followed by what it does:"
)


class Wanted(BaseModel):
    """One item asked for in a supplier order, as spoken."""

    item: str = Field(max_length=100, description="The item, as spoken.")
    quantity: str | None = Field(default=None, max_length=32, description="How many, as spoken: 50, dus.")
    unit: str | None = Field(default=None, max_length=16, description="Unit as spoken: kilo, packet.")


class Choice(BaseModel):
    """The tool the sentence means, with the spoken fields that tool needs and no others.

    Every field is optional but `tool`, because each tool needs a different two or three of them.
    What is missing becomes a question rather than a guess, which is why nothing has a stand-in
    value.
    """

    tool: str = Field(max_length=64, description="The name of the one tool to use.")
    item: str | None = Field(
        default=None, max_length=100, description="For check_stock: the item asked about."
    )
    customer: str | None = Field(
        default=None,
        max_length=100,
        description="For record_payment and get_dues: the person, as spoken, honorific included.",
    )
    amount_rupees: float | None = Field(
        default=None, description="For record_payment: how many rupees came in."
    )
    day: str | None = Field(
        default=None, max_length=10, description="For daily_summary: the day as 2026-09-25, if one was named."
    )
    supplier: str | None = Field(
        default=None, max_length=100, description="For draft_supplier_order: the supplier named, if any."
    )
    items: list[Wanted] | None = Field(
        default=None, max_length=20, description="For draft_supplier_order: what to order, if it was listed."
    )
    draft_id: int | None = Field(
        default=None, description="For confirm_supplier_order: the draft number being agreed to."
    )


class UnknownTool(Exception):
    """The model named a tool this server does not offer. Refused, never guessed at."""

    def __init__(self, named: str):
        self.named = named
        super().__init__(f"{named!r} is not a tool this server offers")


class Unclear(Exception):
    """The chosen tool needs something the sentence did not say. Carries the question to ask."""

    def __init__(self, question: str):
        self.question = question
        super().__init__(question)


def instruction(tools: list[Tool]) -> str:
    """The system prompt: how to choose, then the tools exactly as the server describes them."""
    listed = "\n".join(f"- {tool.name}: {tool.description}" for tool in tools)
    return f"{CHOOSE}\n{listed}"


MAX_CACHED = 256
_choice_cache: dict[str, Choice] = {}


async def choose(utterance: str, tools: list[Tool]) -> Choice:
    """Pick one of these tools for this sentence. One model call, or none on a repeat."""
    key = " ".join(utterance.lower().split())
    if key in _choice_cache:
        return _choice_cache[key]

    choice = await llm.parse(
        prompts.as_data("What the shopkeeper said", utterance),
        Choice,
        system=instruction(tools),
    )
    if choice.tool not in {tool.name for tool in tools}:
        raise UnknownTool(choice.tool)

    if len(_choice_cache) >= MAX_CACHED:
        del _choice_cache[next(iter(_choice_cache))]
    _choice_cache[key] = choice
    log.info("chose %s", choice.tool)
    return choice


def _payment(choice: Choice) -> dict[str, Any]:
    """A payment needs both who and how much; either one missing is a question."""
    if not choice.customer:
        raise Unclear("Who paid?")
    if not choice.amount_rupees:
        raise Unclear("How much did they pay?")
    return {"customer": choice.customer, "amount_rupees": choice.amount_rupees}


def _order(choice: Choice) -> dict[str, Any]:
    """A draft with no items is the briefing's own suggestions, which the tool already handles."""
    asked: dict[str, Any] = {}
    if choice.supplier:
        asked["supplier"] = choice.supplier
    if choice.items:
        asked["items"] = [item.model_dump(exclude_none=True) for item in choice.items]
    return asked


def _confirm(choice: Choice) -> dict[str, Any]:
    """Confirming needs the draft number. A model-invented one would order the wrong goods."""
    if not choice.draft_id:
        raise Unclear("Which draft order should I place?")
    return {"draft_id": choice.draft_id}


def arguments(choice: Choice, utterance: str, key: str) -> dict[str, Any]:
    """The arguments to call the chosen tool with, assembled here rather than taken from the model.

    `record_sale` is handed the sentence word for word: the sale is parsed inside the tool, where
    the quantity check and the catalog are, so nothing the model rewrote can reach the ledger.

    `key` is the idempotency key, made by the host for this one request. The model never supplies
    it, because a key it repeated would silently swallow a real second sale.
    """
    by_tool = {
        "record_sale": lambda: {"utterance": utterance, "idempotency_key": key},
        "record_payment": lambda: {**_payment(choice), "idempotency_key": key},
        "check_stock": lambda: {"item": choice.item} if choice.item else {},
        "get_dues": lambda: {"customer": choice.customer} if choice.customer else {},
        "morning_briefing": dict,
        "draft_supplier_order": lambda: _order(choice),
        "confirm_supplier_order": lambda: {**_confirm(choice), "idempotency_key": key},
        "daily_summary": lambda: {"day": choice.day} if choice.day else {},
    }
    build = by_tool.get(choice.tool)
    if build is None:
        raise UnknownTool(choice.tool)
    return build()
