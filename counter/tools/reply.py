"""What crosses the tool boundary: caps on what comes in, and the shape of what goes out.

Every tool answers twice over. The text is what the assistant reads out at a noisy counter, so it is
one or two sentences. The structured data carries the same facts in machine form, for a card or a
later tool call. They are always the same facts.

The caps live here because this server is meant to be publicly reachable during the demo, with no
login, and because model input is billed. A real spoken command is a sentence; the SDK's own limit is
four megabytes, which is not a limit for a shop.
"""

from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel

MAX_UTTERANCE = 300  # a spoken sale, generously
MAX_NAME = 100  # an item or a person
MAX_KEY = 64  # an idempotency key from the host


def say(text: str, data: BaseModel) -> CallToolResult:
    """Short spoken text first, structured data second."""
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=data.model_dump(mode="json"),
    )
