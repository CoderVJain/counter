"""The three cards: served at the right addresses, safe to render, and speaking the real protocol.

A card renders a customer's nickname, a supplier's note and an item alias, all of which are outside
text, and it renders them inside a host we do not control. So the properties worth testing are
structural: nothing writes markup, nothing reaches the network, and the postMessage handshake is the
one the spec defines rather than one of our own invention. All three are cheap to assert and easy to
miss by eye.
"""

import re

import pytest
from mcp.server.apps import APP_MIME_TYPE

from counter.ui import cards

CARDS = {cards.BRIEFING, cards.ORDER, cards.SUMMARY}

# No test here reaches a model; the mark keeps that true if one of them grows a tool call.
pytestmark = pytest.mark.usefixtures("no_model")

# innerHTML and its relatives turn outside text into elements. document.write is the same hole, older.
WRITES_MARKUP = re.compile(r"innerHTML|outerHTML|document\.write|insertAdjacentHTML")

# A card that can fetch is a card that can leak what it renders, and its CSP grants no origin anyway.
REACHES_OUT = re.compile(r"https?://|//cdn|@import|@font-face|\bsrc\s*=|\bfetch\s*\(|XMLHttpRequest")

# Declarations, not prose: "animation" may appear in a comment explaining why there is none.
MOVES = re.compile(r"@keyframes|(?:animation|transition)(?:-\w+)?\s*:")


@pytest.fixture
def apps():
    return cards.build()


@pytest.fixture
def documents(apps):
    return {binding.resource.uri: binding.resource for binding in apps.resources()}


def test_the_three_cards_are_registered(documents):
    assert set(documents) == CARDS


def test_every_card_is_served_as_an_mcp_app(documents):
    """A host will not render a ui:// resource under any other mime type."""
    assert {resource.mime_type for resource in documents.values()} == {APP_MIME_TYPE}


@pytest.mark.parametrize("uri", sorted(CARDS))
async def test_a_card_reads_back_as_one_whole_document(documents, uri):
    """Style and bridge are inlined, so what the host reads needs nothing else to work."""
    html = await documents[uri].read()
    assert html.startswith("<!doctype html>")
    assert "<title>" in html
    assert cards._STYLE_MARKER not in html
    assert cards._BRIDGE_MARKER not in html
    assert "--brass:" in html
    assert "function render(" in html


@pytest.mark.parametrize("uri", sorted(CARDS))
async def test_a_card_never_writes_markup(documents, uri):
    """Text reaches the page through textContent, which cannot become an element."""
    html = await documents[uri].read()
    assert not WRITES_MARKUP.search(html)
    assert "textContent" in html


@pytest.mark.parametrize("uri", sorted(CARDS))
async def test_a_card_loads_nothing_from_the_network(documents, uri):
    """No webfont, no script, no image: the card has no origin to fetch them from."""
    html = await documents[uri].read()
    assert not REACHES_OUT.search(html)


@pytest.mark.parametrize("uri", sorted(CARDS))
def test_a_card_declares_that_it_needs_no_network(documents, uri):
    """The document asks for nothing, and the CSP says so too for a host that enforces it."""
    assert documents[uri].meta["ui"]["csp"] == {
        "connectDomains": [],
        "resourceDomains": [],
        "frameDomains": [],
        "baseUriDomains": [],
    }


@pytest.mark.parametrize("uri", sorted(CARDS))
async def test_a_card_speaks_the_apps_dialect_and_not_our_own(documents, uri):
    """The handshake the spec defines, so a card renders in a real host and not only in sim_client."""
    html = await documents[uri].read()
    assert "ui/initialize" in html
    assert "ui/notifications/initialized" in html
    assert "ui/notifications/tool-result" in html
    assert "ui/notifications/size-changed" in html


@pytest.mark.parametrize("uri", sorted(CARDS))
async def test_a_card_holds_still(documents, uri):
    """No animation and no transition. Two seconds of glance is not long enough to watch anything."""
    html = await documents[uri].read()
    assert not MOVES.search(html)


def test_the_order_card_says_it_is_simulated(documents):
    """From CLAUDE.md: anything simulated is labelled where it is shown, not only in the README."""
    html = documents[cards.ORDER].text
    assert "Simulated order" in html
    assert "No supplier is contacted" in html


# Everything above tests the documents. What follows tests that a real session actually serves them,
# which is the claim that matters: a card nobody can fetch is not a card.

CARDED_TOOLS = {
    "morning_briefing": cards.BRIEFING,
    "daily_summary": cards.SUMMARY,
    "draft_supplier_order": cards.ORDER,
}


async def test_a_session_lists_the_three_cards(connect):
    async with connect() as client:
        listed = await client.list_resources()
    assert {resource.uri for resource in listed.resources} == CARDS


async def test_the_carded_tools_point_at_their_card(connect):
    """The binding a host reads: _meta.ui.resourceUri on the tool itself."""
    async with connect() as client:
        listed = await client.list_tools()

    bound = {
        tool.name: tool.meta["ui"]["resourceUri"] for tool in listed.tools if tool.meta and "ui" in tool.meta
    }
    assert bound == CARDED_TOOLS


async def test_the_other_five_tools_carry_no_card(connect):
    """A card is a claim that one exists. The five tools without one must not make it."""
    async with connect() as client:
        listed = await client.list_tools()

    for tool in listed.tools:
        if tool.name not in CARDED_TOOLS:
            assert not (tool.meta and "ui" in tool.meta), tool.name


async def test_a_card_can_be_read_back_over_the_session(connect):
    """What a host fetches after seeing resourceUri, and the point where a typo would 404."""
    async with connect() as client:
        result = await client.read_resource(cards.BRIEFING)

    contents = result.contents[0]
    assert contents.mime_type == APP_MIME_TYPE
    assert "ui/initialize" in contents.text
