"""record_sale and record_payment: the two tools that move stock and money.

Both write, so both obey the two rules that matter for a voice interface.

Saying it twice must not do it twice. Speech gets repeated, networks retry, and a shopkeeper who is
not sure the assistant heard will simply say it again. Every call carries a key from the host and the
write runs inside `idempotency.once`, which does the work once and replays the same answer after
that. Four kilos must never leave the shelf because one sentence was heard twice.

A question is not a failure. When the sentence is ambiguous the tool returns the question as an
ordinary reply, so the assistant speaks it and the shopkeeper says a fuller sentence. Only the shop's
own rules - not enough on the shelf, more money than is owed - come back as errors, because those are
refusals rather than questions.

No business rule lives here. Understanding is `agent/`, deciding is `domain/`, phrasing is
`summarizer`. This module only joins them up.
"""

from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from counter.agent import parser, summarizer
from counter.domain import catalog, dates, idempotency, inventory, ledger, sales, units
from counter.domain.db import session
from counter.tools import reply


class SoldLine(BaseModel):
    """One line of a recorded sale, already priced."""

    item: str
    quantity: str
    amount: str


class SaleReply(BaseModel):
    """What record_sale did, or what it needs to know before it can do anything."""

    recorded: bool
    question: str | None = Field(default=None, description="Set when the sale needs one more detail")
    sale_id: int | None = None
    lines: list[SoldLine] = []
    total: str | None = None
    total_paise: int | None = None
    customer: str | None = None
    on_credit: bool = False
    due: str | None = Field(default=None, description="When the credit is due, as a shopkeeper says it")
    already_recorded: bool = Field(default=False, description="True when this key had already been used")


class PaymentReply(BaseModel):
    """What record_payment did to a customer's balance."""

    customer: str
    paid: str
    balance: str
    balance_paise: int
    already_recorded: bool = False


def _asking(question: str) -> CallToolResult:
    """A question, returned as an ordinary reply so the assistant simply speaks it."""
    return reply.say(question, SaleReply(recorded=False, question=question))


def _write_sale(db: Session, sale: parser.ParsedSale) -> dict:
    """Write the sale and describe it as plain data, which is all a replayed result may be."""
    row = sales.record(
        db,
        [(line.item, line.qty_base) for line in sale.lines],
        customer=sale.customer,
        is_credit=sale.is_credit,
        due_date=sale.due_date,
    )
    return SaleReply(
        recorded=True,
        sale_id=row.id,
        lines=[
            SoldLine(
                item=line.item.name,
                quantity=units.from_base(line.item, line.qty_base),
                amount=units.rupees(line.total_paise),
            )
            for line in sale.lines
        ],
        total=units.rupees(sale.total_paise),
        total_paise=sale.total_paise,
        customer=sale.customer.name if sale.customer else None,
        on_credit=sale.is_credit,
        due=dates.spoken(sale.due_date) if sale.due_date else None,
    ).model_dump(mode="json")


def _short(exc: inventory.InsufficientStock) -> str:
    """A refusal a shopkeeper can act on: what was asked for, and what is actually there."""
    have = units.from_base(exc.item, exc.have_base)
    wanted = units.from_base(exc.item, exc.wanted_base)
    return f"There is only {have} {exc.item.name}, not {wanted}. Sell what is there?"


def register(mcp) -> None:
    """Add record_sale and record_payment to the server."""

    @mcp.tool(
        name="record_sale",
        title="Record a sale",
        description=(
            "Record something sold, paid in cash or taken on credit, and take it out of stock. "
            "Call this whenever the shopkeeper says they sold, gave or handed over goods. "
            "Pass the whole sentence exactly as spoken, in Hindi, English or a mix of both - do not "
            "translate it, tidy it or split it up, because the items, quantities, customer and "
            "payment day are all read out of it here. If the reply carries a question, speak the "
            "question and call this again with the fuller sentence rather than guessing."
        ),
    )
    async def record_sale(
        utterance: Annotated[
            str,
            Field(max_length=reply.MAX_UTTERANCE, description="The sale as spoken, word for word."),
        ],
        idempotency_key: Annotated[
            str,
            Field(
                max_length=reply.MAX_KEY,
                description="A unique id for this spoken command, so a repeat is not a second sale.",
            ),
        ],
    ) -> Annotated[CallToolResult, SaleReply]:
        with session() as db:
            try:
                sale = await parser.parse_sale(db, utterance)
            except parser.NeedsClarification as exc:
                return _asking(exc.question)
            except parser.NothingHeard:
                return _asking("What was sold?")

            try:
                stored, replayed = idempotency.once(db, idempotency_key, lambda: _write_sale(db, sale))
            except inventory.InsufficientStock as exc:
                raise ToolError(_short(exc)) from exc

            data = SaleReply.model_validate(stored)
            data.already_recorded = replayed
            facts = summarizer.sale_facts(sale)
            if replayed:
                facts = "Already recorded. " + facts
            return reply.say(await summarizer.say(facts), data)

    @mcp.tool(
        name="record_payment",
        title="Record a payment",
        description=(
            "Record money a customer has paid against what they owe, and say what is left. "
            "Call this when the shopkeeper says someone paid, settled up or gave money back. "
            "Give the customer as spoken, nickname and all, and the amount in rupees."
        ),
    )
    async def record_payment(
        customer: Annotated[
            str,
            Field(max_length=reply.MAX_NAME, description="Who paid, as spoken."),
        ],
        amount_rupees: Annotated[
            float,
            Field(gt=0, le=float(units.MAX_RUPEES), description="How much they paid, in rupees."),
        ],
        idempotency_key: Annotated[
            str,
            Field(
                max_length=reply.MAX_KEY,
                description="A unique id for this spoken command, so a repeat is not a second payment.",
            ),
        ],
    ) -> Annotated[CallToolResult, PaymentReply]:
        with session() as db:
            try:
                who = catalog.find_customer(db, customer)
            except catalog.AmbiguousCustomer as exc:
                names = " or ".join(c.name for c in exc.candidates)
                raise ToolError(f"Which one, {names}?") from exc
            except catalog.UnknownCustomer as exc:
                raise ToolError(f"I do not have {customer} on the books.") from exc

            try:
                paise = units.to_paise(amount_rupees)
            except units.ImpossibleAmount as exc:
                raise ToolError(f"{amount_rupees} is not an amount I can record.") from exc

            def work() -> dict:
                ledger.record_payment(db, who, paise)
                left = ledger.balance(db, who.id)
                return PaymentReply(
                    customer=who.name,
                    paid=units.rupees(paise),
                    balance=units.rupees(left),
                    balance_paise=left,
                ).model_dump(mode="json")

            try:
                stored, replayed = idempotency.once(db, idempotency_key, work)
            except ledger.Overpayment as exc:
                owed = units.rupees(exc.balance_paise)
                raise ToolError(f"{who.name} only owes {owed}. Record that instead?") from exc

            data = PaymentReply.model_validate(stored)
            data.already_recorded = replayed
            facts = f"{data.customer} paid {data.paid}. Balance {data.balance}."
            if replayed:
                facts = "Already recorded. " + facts
            return reply.say(await summarizer.say(facts), data)
