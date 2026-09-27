"""Phase 4's done-when test: a spoken sentence produces a card and one correct write.

The shape here is the shape of the demo. The MCP hop is a real socket, because that is the hop a
judge exercises and the one that has already hidden a framing bug from every in-process test. The
model is scripted, so the whole file costs nothing: what a real Nova Micro picks for a real sentence
is the eval's job, not this test's.

What is pinned is the chain. One sentence in at `/say`, the right tool chosen, the card that tool
promises fetched and handed back, the sentence spoken, and exactly one row written - 2 kg of sugar
gone and a debt in Sharma ji's name, computed by the shop's own code and never by the model.
"""

import asyncio

import httpx2
import pytest

from counter.agent import llm, parser
from counter.config import Settings
from counter.domain import catalog, inventory, ledger
from counter.seed import seed
from counter.server import create_app
from sim_client import app as sim_app
from sim_client import brain, host
from tests.conftest import serve
from tests.fakes import ScriptedModel

SUGAR = "do kilo cheeni Sharma ji ko, kal dega"

# What the model would have answered, for both questions one sale asks it.
SALE_SCRIPTS = {
    "Choice": {"tool": "record_sale"},
    "HeardSale": {
        "lines": [{"item": "cheeni", "qty": "do", "unit": "kilo"}],
        "customer": "Sharma ji",
        "is_credit": True,
        "due_spoken": "kal",
    },
}


@pytest.fixture
def spoken_to(monkeypatch, shop, free_port):
    """Point the simulated host at a real Counter on a real port, with a scripted model.

    The caches are cleared because both outlive a test: a sentence remembered from an earlier one
    would make this test pass without asking anything.
    """
    seed(shop)
    brain._choice_cache.clear()
    parser._heard_cache.clear()
    url = f"http://127.0.0.1:{free_port}/mcp"
    monkeypatch.setattr(host, "settings", lambda: Settings(_env_file=None, counter_mcp_url=url))

    def run(utterance: str, scripts: dict) -> dict:
        model = ScriptedModel(scripts)
        monkeypatch.setattr(llm, "_model", lambda smart=False: model)
        server, thread = serve(create_app(), free_port)

        async def turn() -> dict:
            transport = httpx2.ASGITransport(app=sim_app.app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://localhost:8200") as page:
                answered = await page.post("/say", json={"utterance": utterance})
            answered.raise_for_status()
            return answered.json()

        try:
            return asyncio.run(turn())
        finally:
            server.should_exit = True
            thread.join(timeout=15)

    yield run
    brain._choice_cache.clear()
    parser._heard_cache.clear()


def test_a_spoken_sale_is_recorded_exactly_once_and_correctly(spoken_to, shop):
    """The phase's own bar, end to end: sentence in, tool chosen, one right write out."""
    sugar = catalog.find_item(shop, "cheeni")
    sharma = catalog.find_customer(shop, "Sharma ji")
    in_stock = inventory.on_hand(shop, sugar.id)
    owed = ledger.balance(shop, sharma.id)  # the seed already gives him an open debt

    turn = spoken_to(SUGAR, SALE_SCRIPTS)

    assert turn["tool"] == "record_sale"
    assert turn["ok"]
    assert turn["spoken"]
    assert turn["protocol"] == "2025-11-25", "the page shows this, so the demo proves the version"

    # 2 kg of sugar in the item's own base units, and the debt priced by the shop's own code.
    assert in_stock - inventory.on_hand(shop, sugar.id) == 2 * sugar.base_per_unit
    assert ledger.balance(shop, sharma.id) - owed == 2 * sugar.price_paise


def test_a_briefing_comes_back_with_its_card(spoken_to):
    """A carded tool must hand the page a document, not just a sentence."""
    turn = spoken_to("good morning", {"Choice": {"tool": "morning_briefing"}})

    assert turn["tool"] == "morning_briefing"
    assert turn["data"]["outstanding"]
    assert "ui/initialize" in turn["card_html"], "the card's own bridge should be in the document"


def test_a_tool_without_a_card_answers_in_words_alone(spoken_to):
    turn = spoken_to("kitni cheeni bachi hai", {"Choice": {"tool": "check_stock", "item": "cheeni"}})

    assert turn["tool"] == "check_stock"
    assert turn["card_html"] is None
    assert turn["spoken"]


def test_a_missing_field_comes_back_as_a_question_and_writes_nothing(spoken_to, shop):
    """A payment with no amount must be asked about, not written as zero."""
    before = ledger.outstanding_total(shop)

    turn = spoken_to("Sharma ji ne diye", {"Choice": {"tool": "record_payment", "customer": "Sharma ji"}})

    assert not turn["ok"]
    assert turn["tool"] is None
    assert "how much" in turn["spoken"].lower()
    assert ledger.outstanding_total(shop) == before


def test_a_tool_that_refuses_is_spoken_as_a_question_not_an_error(spoken_to, shop):
    """The server's own clarifying questions have to reach the shopkeeper as speech."""
    turn = spoken_to(
        "Chaudhary sahib ne paanch sau diye",
        {"Choice": {"tool": "record_payment", "customer": "Chaudhary sahib", "amount_rupees": 500}},
    )

    assert not turn["ok"]
    assert turn["spoken"]
    assert turn["card_html"] is None


def test_the_page_carries_the_simulated_label_and_no_amazon_marks():
    """A rule of the hackathon, and the one thing on the page that is not negotiable."""
    page = sim_app.PAGE.read_text(encoding="utf-8")

    assert "not affiliated with Amazon" in page
    assert "Simulated Alexa+ experience" in page
    assert "alexa.png" not in page.lower()


def test_the_page_never_writes_markup_from_a_reply():
    """Customer names and supplier notes reach this page. None of it may become an element."""
    page = sim_app.PAGE.read_text(encoding="utf-8")

    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert banned not in page, banned


def test_a_question_in_the_data_is_shown_as_a_question():
    """The sale tool answers a clarification as an ordinary reply, so `ok` alone misses it."""
    page = sim_app.PAGE.read_text(encoding="utf-8")

    assert "turn.data && turn.data.question" in page


def test_the_card_iframe_is_sandboxed_away_from_this_origin():
    """allow-same-origin would give a card the page's DOM and storage. srcdoc plus scripts only."""
    page = sim_app.PAGE.read_text(encoding="utf-8")

    assert '"sandbox", "allow-scripts"' in page
    assert "allow-scripts allow-same-origin" not in page
