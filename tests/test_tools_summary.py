"""morning_briefing and daily_summary over a real MCP session."""

from datetime import timedelta

import pytest

from counter.domain import dates, inventory, ledger, sales
from counter.domain.models import Customer, Item

pytestmark = pytest.mark.usefixtures("no_model")


@pytest.fixture
def shop_day(shop):
    """Sugar is low, rice is fine, and one credit sale is due today."""
    sugar = Item(
        name="sugar",
        aliases=["cheeni"],
        unit="kg",
        base_unit="g",
        base_per_unit=1000,
        price_paise=4500,
        reorder_level_base=5000,
    )
    rice = Item(
        name="rice",
        aliases=[],
        unit="kg",
        base_unit="g",
        base_per_unit=1000,
        price_paise=6000,
        reorder_level_base=1000,
    )
    sharma = Customer(name="Sharma ji", nicknames=["sharma"])
    shop.add_all([sugar, rice, sharma])
    shop.flush()
    inventory.move(shop, sugar, 3_000, "opening")
    inventory.move(shop, rice, 10_000, "opening")
    shop.commit()
    return shop


async def test_the_briefing_ranks_what_to_buy_and_what_is_due(connect, shop_day):
    sharma = shop_day.get(Customer, 1)
    ledger.add_credit(shop_day, sharma, 20_000, due_date=dates.today())
    shop_day.commit()

    async with connect() as client:
        result = await client.call_tool("morning_briefing", {})

    data = result.structured_content
    assert [line["item"] for line in data["low_stock"]] == ["sugar"]
    assert data["low_stock"][0]["in_stock"] == "3 kg"
    assert data["low_stock"][0]["suggest_buying"] == "7 kg"
    assert data["due_today_total"] == "Rs 200"
    assert data["due_today"][0]["customer"] == "Sharma ji"
    assert "buy 7 kg" in result.content[0].text


async def test_a_quiet_morning_says_so_rather_than_nothing(connect, shop):
    async with connect() as client:
        result = await client.call_tool("morning_briefing", {})

    assert result.structured_content["low_stock"] == []
    assert "Nothing is below its reorder level." in result.content[0].text
    assert "Nothing is due today." in result.content[0].text


async def test_the_day_adds_up_what_was_sold(connect, shop_day):
    sugar = shop_day.get(Item, 1)
    rice = shop_day.get(Item, 2)
    sales.record(shop_day, [(sugar, 1_000)])
    sales.record(shop_day, [(rice, 2_000)])
    shop_day.commit()

    async with connect() as client:
        result = await client.call_tool("daily_summary", {})

    data = result.structured_content
    assert data["sales"] == 2
    assert data["takings"] == "Rs 165"
    assert data["credit_given"] == "Rs 0"
    assert [item["item"] for item in data["top_items"]] == ["rice", "sugar"]
    assert "2 sales, Rs 165 taken" in result.content[0].text


async def test_credit_given_is_counted_apart_from_the_takings(connect, shop_day):
    sugar = shop_day.get(Item, 1)
    sharma = shop_day.get(Customer, 1)
    sales.record(shop_day, [(sugar, 1_000)], customer=sharma, is_credit=True)
    shop_day.commit()

    async with connect() as client:
        result = await client.call_tool("daily_summary", {})

    data = result.structured_content
    assert data["takings"] == "Rs 45"
    assert data["credit_given"] == "Rs 45"
    assert data["outstanding"] == "Rs 45"


async def test_a_day_with_no_sales_is_said_plainly(connect, shop_day):
    yesterday = (dates.today() - timedelta(days=1)).isoformat()

    async with connect() as client:
        result = await client.call_tool("daily_summary", {"day": yesterday})

    assert result.structured_content["sales"] == 0
    assert result.content[0].text == f"No sales recorded for {yesterday}."


async def test_a_day_that_is_not_a_date_asks_which_day(connect, shop_day):
    async with connect() as client:
        result = await client.call_tool("daily_summary", {"day": "kal"})

    assert result.is_error
    assert "Which day?" in result.content[0].text
