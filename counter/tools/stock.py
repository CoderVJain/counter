"""The check_stock tool: what is on the shelf, and how long it will last.

Tool names and descriptions are read by the assistant deciding which tool to call, so they are
written for that reader rather than for us. They are part of the product.

This tool writes nothing, so it needs no repeat protection and no confirmation.
"""

from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult
from pydantic import BaseModel, Field

from counter.domain import catalog, inventory
from counter.domain.db import session
from counter.domain.units import from_base
from counter.tools import reply


class StockLine(BaseModel):
    """One item's position on the shelf."""

    item: str
    quantity: str = Field(description="How much is there, as the shop would say it")
    days_left: float | None = Field(description="Days of stock at the recent rate, null if it never sells")
    below_reorder_level: bool


class StockReport(BaseModel):
    """What check_stock found."""

    lines: list[StockLine]


def _line(db, item) -> StockLine:
    level = inventory.level(db, item)
    return StockLine(
        item=item.name,
        quantity=from_base(item, level.on_hand_base),
        days_left=level.days_of_stock,
        below_reorder_level=level.on_hand_base < item.reorder_level_base,
    )


def _spoken(lines: list[StockLine], asked_for_one: bool) -> str:
    if not lines:
        return "Nothing is running low."
    if asked_for_one:
        one = lines[0]
        if one.days_left is None:
            return f"You have {one.quantity} {one.item}."
        return f"You have {one.quantity} {one.item}, about {one.days_left:.0f} days' worth."
    named = ", ".join(f"{line.quantity} {line.item}" for line in lines[:5])
    return f"Running low on {named}."


def register(mcp) -> None:
    """Add check_stock to the server."""

    @mcp.tool(
        name="check_stock",
        title="Check stock",
        description=(
            "Say how much of an item is left in the shop and roughly how many days it will last. "
            "Call this when the shopkeeper asks what is in stock, how much of something is left, "
            "or what is running low. Give the item as it was spoken, in Hindi or English. "
            "Leave the item out to list everything that has fallen below its reorder level."
        ),
    )
    async def check_stock(
        item: Annotated[
            str | None,
            Field(
                default=None,
                max_length=reply.MAX_NAME,
                description="The item, as spoken. Omit to list everything running low.",
            ),
        ] = None,
    ) -> Annotated[CallToolResult, StockReport]:
        with session() as db:
            if item:
                try:
                    lines = [_line(db, catalog.find_item(db, item))]
                except catalog.AmbiguousItem as exc:
                    names = " or ".join(i.name for i in exc.candidates)
                    raise ToolError(f"Did you mean {names}?") from exc
                except catalog.UnknownItem as exc:
                    raise ToolError(f"There is nothing called {item} in the shop.") from exc
            else:
                lines = [_line(db, level.item) for level in inventory.below_reorder_level(db)]

            spoken = _spoken(lines, asked_for_one=bool(item))
            return reply.say(spoken, StockReport(lines=lines))
