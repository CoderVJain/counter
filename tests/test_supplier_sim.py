"""The fake supplier answers, and says plainly that it is fake.

The labelling is not cosmetic. The hackathon rules require anything simulated to be labelled as
simulated, and a shopkeeper must never believe stock is on its way when it is not.
"""

import httpx
import pytest

from supplier_sim.app import app


@pytest.fixture
async def http():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://supplier") as client:
        yield client


ORDER = {
    "order_id": 1,
    "supplier": "Gupta Traders",
    "lines": [{"item": "sugar", "quantity": "8 kg"}],
}


async def test_an_order_is_accepted_and_referenced(http):
    reply = (await http.post("/orders", json=ORDER)).json()
    assert reply["accepted"] is True
    assert reply["reference"] == "SIM-00001"


async def test_every_reply_says_it_is_simulated(http):
    reply = (await http.post("/orders", json=ORDER)).json()
    assert reply["simulated"] is True
    assert "SIMULATED" in reply["note"]


async def test_an_order_with_no_supplier_is_rejected_by_the_schema(http):
    response = await http.post("/orders", json={"order_id": 1, "lines": []})
    assert response.status_code == 422


async def test_healthz_answers_so_a_dead_sim_is_not_mistaken_for_a_refusal(http):
    assert (await http.get("/healthz")).json()["status"] == "ok"
