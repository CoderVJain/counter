"""A fake supplier, so the ordering flow is end to end without ordering anything.

Nothing here reaches a real wholesaler. Every reply says so, in a field and in the note the assistant
may read out, because the hackathon rules require anything simulated to be labelled as simulated and
because a shopkeeper must never believe stock is on its way when it is not.

It is a separate application on its own port on purpose: Counter talks to it over HTTP exactly as it
would talk to a real supplier, so swapping in a real one later is a URL, not a rewrite.
"""

from datetime import date, timedelta

from fastapi import FastAPI
from pydantic import BaseModel, Field

SIMULATED = "SIMULATED - no real order was placed"
LEAD_TIME_DAYS = 2
MAX_LINES = 50


class OrderLine(BaseModel):
    """One line of an incoming order."""

    item: str = Field(max_length=100)
    quantity: str = Field(max_length=32)


class Order(BaseModel):
    """An order as Counter sends it."""

    order_id: int
    supplier: str = Field(max_length=120)
    lines: list[OrderLine] = Field(max_length=MAX_LINES)


class Accepted(BaseModel):
    """What the fake supplier says back."""

    accepted: bool
    simulated: bool
    reference: str
    expected: date
    note: str


app = FastAPI(title="Supplier sim")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness check, so the demo can tell a dead sim from a refused order."""
    return {"status": "ok", "simulated": "yes"}


@app.post("/orders")
def place(order: Order) -> Accepted:
    """Accept any order and promise it for the day after tomorrow. Always simulated."""
    return Accepted(
        accepted=True,
        simulated=True,
        reference=f"SIM-{order.order_id:05d}",
        expected=date.today() + timedelta(days=LEAD_TIME_DAYS),
        note=f"{SIMULATED}. {len(order.lines)} lines for {order.supplier}.",
    )
