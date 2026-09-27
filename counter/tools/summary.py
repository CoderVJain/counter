"""morning_briefing and daily_summary: the two tools that read a whole day at once.

Both are reads, and both are assembled the same way. Code gathers the figures and formats every one
of them; the model is handed those finished facts and asked only to phrase them. `summarizer.say`
falls back to the facts themselves if a model is unavailable, so a throttled provider costs the
shopkeeper a tidy sentence and never a number.

The briefing ranks the reorder list through `forecaster`, which sorts by days of stock left, because
"urgent" has a definition and a model ranking by feel would spend the shop's cash on slow movers.
`forecaster.explain` is deliberately not used here: it raises when no model answers, and the briefing
has to survive that. Only its facts are borrowed, and the one spoken sentence is built below.
"""

from datetime import date
from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult
from pydantic import BaseModel, Field

from counter.agent import forecaster, summarizer
from counter.domain import dates, ledger, orders, reports, units
from counter.domain.db import session
from counter.tools import reply
from counter.tools.credit import DueLine, due_line
from counter.ui import cards


class LowStockLine(BaseModel):
    """One item worth reordering, with the figures that justify it."""

    item: str
    in_stock: str
    days_left: float | None
    suggest_buying: str


class Briefing(BaseModel):
    """What a shopkeeper needs to know before opening the shutter."""

    low_stock: list[LowStockLine]
    due_today: list[DueLine]
    due_today_total: str
    outstanding: str
    outstanding_paise: int


class SoldItem(BaseModel):
    """One item's contribution to a day."""

    item: str
    quantity: str
    amount: str


class DayReport(BaseModel):
    """A day at the counter, every figure counted in code."""

    day: date
    sales: int
    takings: str
    takings_paise: int
    credit_given: str
    top_items: list[SoldItem]
    outstanding: str
    outstanding_paise: int


def build_briefing(db) -> Briefing:
    """Assemble the briefing from the database. Pure code: no model, so it cannot be throttled.

    Shared with `jobs.briefing`, which needs the same figures on a schedule. Keeping one assembly
    means the scheduled briefing and the spoken one can never disagree.
    """
    today = dates.today()
    ranked = forecaster.by_urgency(orders.suggest_reorder(db))
    low = [
        LowStockLine(
            item=s.item.name,
            in_stock=units.from_base(s.item, s.on_hand_base),
            days_left=s.days_of_stock,
            suggest_buying=units.from_base(s.item, s.qty_base),
        )
        for s in ranked
    ]
    dues = [due_line(db, due, today) for due in ledger.due_by(db, today)]
    due_total = sum(line.amount_paise for line in dues)
    outstanding = ledger.outstanding_total(db)
    return Briefing(
        low_stock=low,
        due_today=dues,
        due_today_total=units.rupees(due_total),
        outstanding=units.rupees(outstanding),
        outstanding_paise=outstanding,
    )


def briefing_facts(briefing: Briefing) -> str:
    """The briefing as plain facts, already ranked and already formatted."""
    parts = []
    if briefing.low_stock:
        low = ". ".join(
            f"{line.item}: {line.in_stock} left, buy {line.suggest_buying}" for line in briefing.low_stock
        )
        parts.append(f"Low stock. {low}.")
    else:
        parts.append("Nothing is below its reorder level.")

    if briefing.due_today:
        names = ", ".join(dict.fromkeys(line.customer for line in briefing.due_today))
        parts.append(f"{briefing.due_today_total} due today, from {names}.")
    else:
        parts.append("Nothing is due today.")

    parts.append(f"{briefing.outstanding} outstanding in total.")
    return " ".join(parts)


def _day_facts(report: DayReport) -> str:
    """A day as plain facts. Every figure here is already a string, so none can be recomputed."""
    if not report.sales:
        return f"No sales recorded for {report.day.isoformat()}."
    parts = [f"{report.sales} sales, {report.takings} taken, {report.credit_given} of it on credit."]
    if report.top_items:
        best = ", ".join(f"{item.quantity} {item.item}" for item in report.top_items)
        parts.append(f"Best sellers: {best}.")
    parts.append(f"{report.outstanding} still outstanding.")
    return " ".join(parts)


def register(apps) -> None:
    """Add morning_briefing and daily_summary, both of which carry a card.

    Takes the `Apps` extension rather than the server, because a card-bound tool has to exist before
    `MCPServer` is constructed: the constructor reads the extension once and never looks again.
    """

    @apps.tool(
        resource_uri=cards.BRIEFING,
        name="morning_briefing",
        title="Morning briefing",
        description=(
            "The shop's standing start: what has run low, how much to reorder and what credit is "
            "due today. Call this when the shopkeeper says good morning, asks what needs doing, "
            "what to order, or for the day's briefing. Writes nothing and orders nothing - use "
            "draft_supplier_order to act on it."
        ),
    )
    async def morning_briefing() -> Annotated[CallToolResult, Briefing]:
        with session() as db:
            briefing = build_briefing(db)
            return reply.say(await summarizer.say(briefing_facts(briefing)), briefing)

    @apps.tool(
        resource_uri=cards.SUMMARY,
        name="daily_summary",
        title="How the day went",
        description=(
            "Say how a day went: how many sales, what was taken, how much of it on credit, the "
            "best sellers and what is still owed. Call this when the shopkeeper asks how today or "
            "a particular day was, or for the day's total. Give the day as a date like 2026-09-25; "
            "leave it out for today."
        ),
    )
    async def daily_summary(
        day: Annotated[
            str | None,
            Field(
                default=None,
                max_length=10,
                description="The day, as 2026-09-25. Omit for today.",
            ),
        ] = None,
    ) -> Annotated[CallToolResult, DayReport]:
        if day:
            try:
                wanted = date.fromisoformat(day)
            except ValueError as exc:
                raise ToolError(f"I could not read {day} as a date. Which day?") from exc
        else:
            wanted = dates.today()

        with session() as db:
            summary = reports.for_day(db, wanted)
            report = DayReport(
                day=summary.day,
                sales=summary.sale_count,
                takings=units.rupees(summary.takings_paise),
                takings_paise=summary.takings_paise,
                credit_given=units.rupees(summary.credit_given_paise),
                top_items=[
                    SoldItem(
                        item=seller.item.name,
                        quantity=units.from_base(seller.item, seller.qty_base),
                        amount=units.rupees(seller.total_paise),
                    )
                    for seller in summary.top_sellers
                ],
                outstanding=units.rupees(summary.outstanding_paise),
                outstanding_paise=summary.outstanding_paise,
            )
            return reply.say(await summarizer.say(_day_facts(report)), report)
