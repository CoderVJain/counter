"""check_stock over a real MCP session: what is on the shelf, and what is running low."""

import pytest

from counter.domain import inventory
from counter.domain.models import Item


@pytest.fixture
def stocked(shop):
    sugar = Item(
        name="sugar",
        aliases=["cheeni"],
        unit="kg",
        base_unit="g",
        price_paise=4500,
        base_per_unit=1000,
        reorder_level_base=2000,
    )
    rice = Item(
        name="rice",
        aliases=[],
        unit="kg",
        base_unit="g",
        price_paise=6000,
        base_per_unit=1000,
        reorder_level_base=5000,
    )
    shop.add_all([sugar, rice])
    shop.flush()
    inventory.move(shop, sugar, 10_000, "opening")
    inventory.move(shop, rice, 1_000, "opening")
    shop.commit()
    return shop


async def test_named_item_reports_its_quantity(connect, stocked):
    async with connect() as client:
        result = await client.call_tool("check_stock", {"item": "cheeni"})
    line = result.structured_content["lines"][0]
    assert line["item"] == "sugar"
    assert line["quantity"] == "10 kg"
    assert "10 kg sugar" in result.content[0].text


async def test_no_item_lists_only_what_is_low(connect, stocked):
    async with connect() as client:
        result = await client.call_tool("check_stock", {})
    assert [line["item"] for line in result.structured_content["lines"]] == ["rice"]


async def test_unknown_item_is_a_spoken_refusal(connect, stocked):
    async with connect() as client:
        result = await client.call_tool("check_stock", {"item": "caviar"})
    assert result.is_error
    assert "caviar" in result.content[0].text
