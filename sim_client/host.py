"""The client half: how the simulated host talks to Counter's MCP server.

This is a real MCP client over Streamable HTTP, the same SDK a judge would point at the server, so
the demo exercises the wire and not a shortcut past it. Nothing about the shop is known here: the
tools, their descriptions and their cards all arrive from the server, which is the whole point of an
add-on.

**The Apps extension is advertised by hand.** The SDK ships the server half of MCP Apps but no client
helper, so support is declared as an identifier and a mime type. The server's `client_supports_apps`
reads exactly that, and a host that does not advertise it is answered with text alone.

A connection is opened per utterance rather than held. The server is stateless between requests, a
card is nine kilobytes of local HTTP, and a host that reconnects is the honest thing to test: a
long-lived client would hide a handshake that only works the first time.

Nothing here logs an utterance, a customer or an amount. Tool names and counts only.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.client import Client
from mcp.client.extension import advertise

from counter.config import settings

log = logging.getLogger(__name__)

APPS_EXTENSION = "io.modelcontextprotocol/ui"
APP_MIME_TYPE = "text/html;profile=mcp-app"


@dataclass(frozen=True)
class Tool:
    """One tool as the brain sees it, straight from `tools/list`."""

    name: str
    title: str
    description: str
    card: str | None


@dataclass(frozen=True)
class Answer:
    """What one tool call produced: what to say, what it means, and what to draw.

    A tool that refuses - an unknown customer, stock that would go negative - answers with `ok`
    false and the question in `spoken`. That is not a failure to report; it is the clarifying
    question the whole design prefers to a guess, so it is spoken like any other answer.
    """

    spoken: str
    data: dict[str, Any] | None
    card_html: str | None
    ok: bool = True


def _card_of(meta: dict[str, Any] | None) -> str | None:
    """The `ui://` address a tool promises a card at, if it promises one."""
    if not meta:
        return None
    return meta.get("ui", {}).get("resourceUri")


class Host:
    """A connected session. Lists the tools, calls one, and fetches the card it points at."""

    def __init__(self, client: Client):
        self._client = client

    @property
    def protocol_version(self) -> str:
        """What the handshake settled on. Shown on the page, so the demo proves the version."""
        return self._client.protocol_version

    async def tools(self) -> list[Tool]:
        """Every tool the server offers, in the order it offers them."""
        listed = await self._client.list_tools()
        return [
            Tool(
                name=tool.name,
                title=tool.title or tool.name,
                description=tool.description or "",
                card=_card_of(tool.meta),
            )
            for tool in listed.tools
        ]

    async def card(self, uri: str) -> str:
        """One card's HTML. Raises if the address serves something that is not a card."""
        result = await self._client.read_resource(uri)
        contents = result.contents[0]
        if contents.mime_type != APP_MIME_TYPE:
            raise ValueError(f"{uri} is {contents.mime_type}, not a card")
        return contents.text

    async def call(self, tool: Tool, arguments: dict[str, Any]) -> Answer:
        """Run one tool and collect everything the page needs from it."""
        result = await self._client.call_tool(tool.name, arguments)
        spoken = " ".join(block.text for block in result.content if getattr(block, "text", None))
        if result.is_error:
            log.info("%s answered with a question", tool.name)
            return Answer(spoken=spoken, data=None, card_html=None, ok=False)
        html = await self.card(tool.card) if tool.card else None
        return Answer(spoken=spoken, data=result.structured_content, card_html=html)


@asynccontextmanager
async def connect(url: str | None = None) -> AsyncIterator[Host]:
    """Open a session with Counter, advertising that this host can render cards."""
    extensions = [advertise(APPS_EXTENSION, {"mimeTypes": [APP_MIME_TYPE]})]
    async with Client(url or settings().counter_mcp_url, extensions=extensions) as client:
        yield Host(client)
