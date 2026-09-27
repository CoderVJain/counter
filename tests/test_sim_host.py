"""The host's client half, driven against a real server on a real port.

Everything here goes over a socket on purpose. An in-process transport would prove that our client
and our server agree with each other, which is not the claim: the claim is that an ordinary MCP
client, advertising MCP Apps the way the SDK allows, gets the tools, the cards and the answers.
"""

import asyncio

import pytest

from counter.seed import seed
from counter.server import create_app
from sim_client import host
from tests.conftest import serve

pytestmark = pytest.mark.usefixtures("no_model")

CARDED = {"morning_briefing", "draft_supplier_order", "daily_summary"}


def drive(port: int, work):
    """Run one coroutine against a real server, and always stop the server afterwards."""
    server, thread = serve(create_app(), port)
    try:
        return asyncio.run(work(f"http://127.0.0.1:{port}/mcp"))
    finally:
        server.should_exit = True
        thread.join(timeout=15)


def test_the_host_lists_every_tool_with_its_card(shop, free_port):
    async def work(url):
        async with host.connect(url) as counter:
            return counter.protocol_version, await counter.tools()

    version, tools = drive(free_port, work)

    assert version == "2025-11-25"
    assert len(tools) == 8
    assert {t.name for t in tools if t.card} == CARDED
    assert all(t.description for t in tools), "the brain chooses on these"


def test_the_host_fetches_a_card_behind_a_tool(shop, free_port):
    """A tool's resourceUri is a promise. This is the host keeping the host's half of it."""

    async def work(url):
        async with host.connect(url) as counter:
            briefing = next(t for t in await counter.tools() if t.name == "morning_briefing")
            return await counter.card(briefing.card)

    html = drive(free_port, work)

    assert "ui/notifications/tool-result" in html


def test_a_tool_call_comes_back_as_speech_data_and_a_card(shop, free_port):
    seed(shop)

    async def work(url):
        async with host.connect(url) as counter:
            briefing = next(t for t in await counter.tools() if t.name == "morning_briefing")
            return await counter.call(briefing, {})

    answer = drive(free_port, work)

    assert answer.spoken
    assert "outstanding" in answer.data
    assert answer.card_html and "ui/initialize" in answer.card_html


def test_a_tool_without_a_card_returns_none_rather_than_pretending(shop, free_port):
    seed(shop)

    async def work(url):
        async with host.connect(url) as counter:
            stock = next(t for t in await counter.tools() if t.name == "check_stock")
            return await counter.call(stock, {})

    answer = drive(free_port, work)

    assert answer.spoken
    assert answer.card_html is None
