"""The shop's three cards, as MCP Apps resources.

A card is one HTML document served at a `ui://` address with the mime type
`text/html;profile=mcp-app`. A host reads it, renders it in a sandboxed iframe, and posts the tool's
structured content in over `postMessage`; the card draws that once and reports its height. Nothing
here computes anything, because every amount and quantity already arrives from `counter/tools/` as a
formatted string.

Each document is assembled from three files in `cards/`: its own markup and render function, the
shared `base.css`, and the shared `bridge.js` that speaks the protocol. The two shared files are
inlined rather than linked, because a card has no origin to fetch them from — the spec is blunt that
every network request, even to localhost, needs a CSP entry, and `_NO_NETWORK` below grants none.

Two rules the documents must keep, both enforced by `tests/test_cards.py`:

1. **Text goes in with `textContent`.** A customer's nickname, a supplier's note and an item alias
   are all outside text. `innerHTML` on any of them is an injection.
2. **Nothing loads from the network.** No font, no script, no image.
"""

from pathlib import Path

from mcp.server.apps import Apps, ResourceCsp

BRIEFING = "ui://counter/briefing.html"
ORDER = "ui://counter/order.html"
SUMMARY = "ui://counter/summary.html"

_CARDS = Path(__file__).parent / "cards"
_STYLE_MARKER = "<!--STYLE-->"
_BRIDGE_MARKER = "<!--BRIDGE-->"

# Empty lists are the point: a card that can reach nothing cannot leak what it renders.
_NO_NETWORK = ResourceCsp(
    connect_domains=[],
    resource_domains=[],
    frame_domains=[],
    base_uri_domains=[],
)


def _read(name: str) -> str:
    return (_CARDS / name).read_text(encoding="utf-8")


def document(name: str) -> str:
    """One card, with the shared stylesheet and protocol bridge inlined into it."""
    html = _read(name)
    html = html.replace(_STYLE_MARKER, f"<style>\n{_read('base.css')}</style>")
    return html.replace(_BRIDGE_MARKER, f"<script>\n{_read('bridge.js')}</script>")


def build() -> Apps:
    """The extension to hand `MCPServer(extensions=[...])`.

    Resources are registered here and tools bind to them in `counter/tools/`. A tool naming an
    address that was never registered raises when the server starts, not when a card is opened.
    """
    apps = Apps()
    apps.add_html_resource(
        BRIEFING,
        document("briefing.html"),
        title="Morning briefing",
        description="What is running out, who owes money today, and the total outstanding.",
        csp=_NO_NETWORK,
    )
    apps.add_html_resource(
        ORDER,
        document("order.html"),
        title="Draft order",
        description="A draft supplier order awaiting spoken confirmation. The order is simulated.",
        csp=_NO_NETWORK,
    )
    apps.add_html_resource(
        SUMMARY,
        document("summary.html"),
        title="Day summary",
        description="A day's takings, best sellers, credit given and the balance still owed.",
        csp=_NO_NETWORK,
    )
    return apps
