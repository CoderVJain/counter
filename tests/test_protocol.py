"""The eligibility test. This one decides whether Counter can be submitted at all.

Two of the hackathon's hard requirements are only provable here:

1. The MCP SDK is imported and genuinely called at runtime. A real client completes a real handshake
   against our own server and gets our own tools back. Naming the SDK in a README would not.
2. The session speaks spec 2025-11-25 or later over Streamable HTTP - one address handling POST and
   GET - rather than stdio or the older HTTP-with-SSE.

`tests/test_protocol_version.py` checks a constant in the library, which is a weaker claim than it
looks: the library's newest revision is 2026-07-28, while a client actually settles on 2025-11-25.
This test asserts what a live session agreed, and compares through the library's own helper rather
than comparing dates as text, because a future revision is not promised to be date-shaped.

This must run in CI.
"""

import asyncio
import socket
import threading
import time

import httpx
import httpx2
import pytest
import uvicorn
from mcp.client import Client
from mcp_types.version import is_version_at_least

from counter.server import create_app

REQUIRED_VERSION = "2025-11-25"

TOOLS = {
    "record_sale",
    "record_payment",
    "check_stock",
    "get_dues",
    "morning_briefing",
    "draft_supplier_order",
    "confirm_supplier_order",
    "daily_summary",
}

pytestmark = pytest.mark.usefixtures("no_model")


@pytest.fixture
def free_port() -> int:
    """A port the operating system says is free, so tests never collide with a real server."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def serve(app, port: int):
    """Start one real uvicorn server in a thread and wait until it is listening."""
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    return server, thread


async def test_a_live_session_agrees_on_the_required_protocol(connect):
    async with connect() as client:
        agreed = client.protocol_version
    assert is_version_at_least(agreed, REQUIRED_VERSION), agreed


async def test_all_eight_tools_are_offered(connect):
    async with connect() as client:
        listed = await client.list_tools()
    assert {tool.name for tool in listed.tools} == TOOLS


async def test_every_tool_describes_itself_for_the_assistant_choosing_one(connect):
    """The description is how Alexa+ picks a tool, so an empty one is a product defect."""
    async with connect() as client:
        listed = await client.list_tools()
    for tool in listed.tools:
        assert tool.description and len(tool.description) > 80, tool.name


async def test_the_handshake_settles_on_the_required_version(connect):
    """An assistant that uses the initialize handshake, rather than the newer probe, agrees on this.

    The newer probe and the handshake are both real, so both are checked: a host that only knows the
    handshake must still reach 2025-11-25 exactly.
    """
    async with connect(mode="legacy") as client:
        assert client.protocol_version == REQUIRED_VERSION


def test_a_client_on_its_default_settings_works_over_a_real_socket(shop, free_port):
    """The test that matters most, and the only one that needs a real server.

    A host connects with its defaults, so that is what has to work. Framing faults are invisible to a
    test that drives the app in process: both `json_response=True` and the newer protocol era answered
    perfectly in process and sent a malformed reply over a socket, while every other test passed. This
    one drives a real client against a real port, all the way to the tool list.
    """
    app = create_app()
    server, thread = serve(app, free_port)
    try:

        async def drive() -> tuple[str, set[str]]:
            async with Client(f"http://127.0.0.1:{free_port}/mcp") as client:
                listed = await client.list_tools()
                return client.protocol_version, {tool.name for tool in listed.tools}

        agreed, names = asyncio.run(drive())
    finally:
        server.should_exit = True
        thread.join(timeout=15)

    assert agreed == REQUIRED_VERSION
    assert names == TOOLS


def test_a_real_socket_returns_a_framed_body_and_not_just_headers(shop, free_port):
    """The same failure seen at the byte level, so a regression says what broke rather than hanging.

    A correct reply either carries a content-length with its body, or frames the body as chunks. The
    broken shape was a chunked reply whose body was written raw, which a client cannot parse.
    """
    app = create_app()
    server, thread = serve(app, free_port)
    try:
        response = httpx.post(
            f"http://127.0.0.1:{free_port}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": REQUIRED_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
            headers={"content-type": "application/json", "accept": "application/json, text/event-stream"},
            timeout=10,
        )
        health = httpx.get(f"http://127.0.0.1:{free_port}/healthz", timeout=10)
    finally:
        server.should_exit = True
        thread.join(timeout=15)

    assert response.status_code == 200
    assert response.text, "the endpoint sent headers and no body"
    assert "counter" in response.text
    assert health.json() == {"status": "ok"}


def test_a_modern_era_probe_is_answered_on_the_path_that_works(shop, free_port):
    """A probe for the 2026-07-28 era must be answered, not half-answered.

    The SDK would route it to a handler whose reply is malformed over a socket, so `HandshakeOnly`
    keeps it on the event-stream path. Whatever the answer says, it has to be readable, because a
    client that cannot read it never gets as far as the handshake.
    """
    app = create_app()
    server, thread = serve(app, free_port)
    try:
        response = httpx.post(
            f"http://127.0.0.1:{free_port}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
            headers={
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
                "mcp-protocol-version": "2026-07-28",
            },
            timeout=10,
        )
    finally:
        server.should_exit = True
        thread.join(timeout=15)

    assert response.text, "the probe reply was lost on the wire"


async def test_a_request_from_an_unnamed_host_is_turned_away(shop):
    """The SDK's protection against disguised requests. The fix for a tunnel is to name the address,
    never to switch this off, so a change that weakened it should fail here."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://evil.example") as http:
            response = await http.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                headers={"content-type": "application/json", "accept": "application/json"},
            )

    assert response.status_code == 421
