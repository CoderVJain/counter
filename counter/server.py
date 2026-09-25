"""The MCP server: one HTTP address that an assistant can drive the shop through.

Counter is an Alexa+ add-on, and an add-on is an MCP server. The assistant hears the shopkeeper,
reads the tool descriptions below, picks one and calls it. Everything after that is ours.

Four details here are easy to get wrong and expensive to debug, so they are spelled out:

1. The MCP application is built **before** the FastAPI one, because building it is what creates the
   session manager, and the session manager has to be started from our own startup. FastAPI does not
   start a mounted application's background work, so without this the endpoint answers nothing.
2. The SDK refuses requests whose Host header it does not recognise. Left alone it trusts only
   localhost, so every request through a tunnel or Render is turned away. `PUBLIC_HOST` names the
   outside address. The fix is to name the address, never to switch the check off.
3. The MCP application is mounted last, because it claims anything not already matched.
4. Every reply must be framed as an event stream, which means `json_response=True` is **not** passed
   and `HandshakeOnly` keeps requests off the newer protocol era. Behind a real server, a reply that
   this stack writes as a single JSON body is malformed on the wire: measured on 25 Sep with mcp
   2.1.1 and uvicorn 0.53, the response declares `transfer-encoding: chunked` and then writes the
   body without chunk framing, so the client sees a broken response and reports "peer unexpectedly
   closed connection". The event-stream replies are framed correctly and arrive. None of this is
   visible in tests that drive the app in process, so tests/test_protocol.py boots a real socket.

An event stream here is not a held-open connection: the reply arrives and the response ends, so
there is nothing for a tunnel or free hosting to cut. Sessions are not kept between requests, so
more than one copy of this server can run at once.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS

from counter.config import settings
from counter.tools import credit, orders, sales, stock, summary

LOCAL_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
LOCAL_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]

MCP_PATH = "/mcp"
PROTOCOL_VERSION_HEADER = b"mcp-protocol-version"
HANDSHAKE_VERSIONS = {version.encode() for version in HANDSHAKE_PROTOCOL_VERSIONS}

INSTRUCTIONS = (
    "The back office of a small Indian shop. Use these tools to record sales and payments, check "
    "stock, chase credit and order from suppliers. Speech may mix Hindi and English; pass it "
    "through as spoken rather than translating it."
)


def _transport_security() -> TransportSecuritySettings:
    """Trust localhost, and the public address too when one is configured."""
    public = settings().public_host.strip()
    hosts = [*LOCAL_HOSTS]
    origins = [*LOCAL_ORIGINS]
    if public:
        hosts.append(public)
        origins.extend([f"https://{public}", f"http://{public}"])
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


class HandshakeOnly:
    """Hide the newer protocol era from the MCP app, so every request takes the path that works.

    The SDK routes on the `mcp-protocol-version` header: a value it does not recognise as a handshake
    version goes to the 2026-07-28 per-request handler, which answers with a single JSON body. Behind
    a real server those replies never arrive. Measured on 25 Sep with mcp 2.1.1 and uvicorn 0.53: the
    reply is written with `transfer-encoding: chunked` but the body is not chunk-framed, so the client
    sees a malformed response and reports "peer unexpectedly closed connection". A reply framed as an
    event stream, which is what the handshake path sends, is framed correctly and arrives.

    Dropping the header means such a request is handled as an ordinary one. A client that probed for
    the newer era gets the same answer any older server gives it, and does what it does with any
    older server: it falls back to the initialize handshake and negotiates 2025-11-25, the version the
    hackathon requires.

    This is plain ASGI on purpose. A Starlette http middleware would re-stream every response, and a
    re-streamed response is exactly what loses its framing here. This one only edits the request.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            headers = [
                (name, value)
                for name, value in scope["headers"]
                if name.lower() != PROTOCOL_VERSION_HEADER or value in HANDSHAKE_VERSIONS
            ]
            scope = {**scope, "headers": headers}
        await self.app(scope, receive, send)


def build_mcp() -> MCPServer:
    """The MCP server with every tool registered on it."""
    mcp = MCPServer(
        name="counter",
        title="Counter",
        version="0.1.0",
        instructions=INSTRUCTIONS,
    )
    credit.register(mcp)
    orders.register(mcp)
    sales.register(mcp)
    stock.register(mcp)
    summary.register(mcp)
    return mcp


def create_app() -> FastAPI:
    """Build the whole server. A factory because a session manager runs exactly once.

    Each call produces an independent server, which is what lets a test start one per test rather
    than sharing a manager that refuses to start twice.
    """
    mcp = build_mcp()

    # Must come before the FastAPI app: this call creates the session manager used in the lifespan.
    mcp_app = mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        transport_security=_transport_security(),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Run the MCP session manager. Without this the endpoint accepts nothing."""
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="Counter", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness check for the host we deploy to."""
        return {"status": "ok"}

    # Mounted last: this route claims everything not already matched above.
    app.mount("/", HandshakeOnly(mcp_app))
    return app


app = create_app()
