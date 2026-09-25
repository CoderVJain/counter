"""get_dues: who owes what, and what is due today.

Reads only. Which entries a payment has already settled is worked out by `ledger.open_dues`, oldest
due date first, so nothing here decides what is still owed.

Asked about one customer, this answers for them. Asked about nobody, it answers the question a
shopkeeper actually means at opening time - what is due today - rather than listing the whole book.
"""

from datetime import date
from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from counter.domain import catalog, dates, ledger, units
from counter.domain.db import session
from counter.domain.ledger import Due
from counter.domain.models import Customer
from counter.tools import reply


class DueLine(BaseModel):
    """One unsettled charge and what remains on it."""

    customer: str
    amount: str
    amount_paise: int
    due: str | None = Field(description="When it is due, as a shopkeeper says it, or null if no day was set")
    overdue: bool


class DuesReport(BaseModel):
    """What is owed, and what it comes to."""

    lines: list[DueLine]
    total: str
    total_paise: int


def due_line(db: Session, due: Due, today: date) -> DueLine:
    """One due as the host sees it. Public because morning_briefing shows the same fact."""
    customer = db.get(Customer, due.entry.customer_id)
    return DueLine(
        customer=customer.name,
        amount=units.rupees(due.remaining_paise),
        amount_paise=due.remaining_paise,
        due=dates.spoken(due.due_date) if due.due_date else None,
        overdue=bool(due.due_date and due.due_date < today),
    )


def _spoken_one(name: str, report: DuesReport) -> str:
    if not report.lines:
        return f"{name} owes nothing."
    soonest = report.lines[0]
    when = f", {soonest.amount} due {soonest.due}" if soonest.due else ""
    return f"{name} owes {report.total}{when}."


def _spoken_all(report: DuesReport) -> str:
    if not report.lines:
        return "Nothing is due today."
    names = ", ".join(dict.fromkeys(line.customer for line in report.lines))
    return f"{report.total} due today, from {names}."


def register(mcp) -> None:
    """Add get_dues to the server."""

    @mcp.tool(
        name="get_dues",
        title="Check credit owed",
        description=(
            "Say what a customer owes on credit and when it is due. Call this when the shopkeeper "
            "asks who owes money, how much someone owes, what is due today, or about udhaar. Give "
            "the customer as spoken, nickname and all. Leave the customer out to hear everything "
            "that is due today or already late."
        ),
    )
    async def get_dues(
        customer: Annotated[
            str | None,
            Field(
                default=None,
                max_length=reply.MAX_NAME,
                description="Who to check, as spoken. Omit for everything due today.",
            ),
        ] = None,
    ) -> Annotated[CallToolResult, DuesReport]:
        today = dates.today()
        with session() as db:
            if customer:
                try:
                    who = catalog.find_customer(db, customer)
                except catalog.AmbiguousCustomer as exc:
                    names = " or ".join(c.name for c in exc.candidates)
                    raise ToolError(f"Which one, {names}?") from exc
                except catalog.UnknownCustomer as exc:
                    raise ToolError(f"I do not have {customer} on the books.") from exc
                dues = ledger.open_dues(db, who.id)
            else:
                dues = ledger.due_by(db, today)

            lines = [due_line(db, due, today) for due in dues]
            total = sum(line.amount_paise for line in lines)
            report = DuesReport(lines=lines, total=units.rupees(total), total_paise=total)
            spoken = _spoken_one(who.name, report) if customer else _spoken_all(report)
            return reply.say(spoken, report)
