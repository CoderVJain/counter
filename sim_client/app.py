"""The simulated Alexa+ host: a page that listens, a route that acts.

The real thing is out of reach - the Alexa+ MCP Toolkit, its CLI and its device simulator are
partner-gated and US-only - and the hackathon rules allow a simulated host instead. This is that
host, and it is deliberately the thin part: it hears a sentence, asks `brain` which tool it means,
calls that tool over MCP, and renders whatever comes back. Every shop decision belongs to the
server.

Two things are free on purpose. Speech in and speech out are the browser's own `SpeechRecognition`
and `speechSynthesis`, so there is no speech bill and no key. The only billed call in a turn is the
tool choice, and that one is cached.

**This is a development host and must never be tunnelled.** It has no authentication, and it holds a
session to a server that has none either. Only `:8000` is ever exposed.

Nothing here logs an utterance, a customer or an amount: tool names and outcomes only, the same rule
`agent/` and `tools/` already keep.
"""

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from counter.tools.reply import MAX_UTTERANCE
from sim_client import brain, host

log = logging.getLogger(__name__)

# Uvicorn configures its own loggers and leaves ours silent, so without this the host says nothing
# about which tool it chose - which is the one line worth watching while the demo runs. What is
# logged stays names and outcomes: never an utterance, a customer or an amount.
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

PAGE = Path(__file__).parent / "page.html"

app = FastAPI(title="Counter - simulated Alexa+ host")


class Said(BaseModel):
    """One spoken sentence, capped at the length the server itself accepts."""

    utterance: str = Field(min_length=1, max_length=MAX_UTTERANCE)


class Turn(BaseModel):
    """What the page needs to finish a turn: what to say, what was used, what to draw."""

    spoken: str
    tool: str | None = None
    data: dict[str, Any] | None = None
    card_html: str | None = None
    ok: bool = True
    # What the handshake settled on. The page shows it, so the required spec version is visible in
    # the demo rather than asserted in a README.
    protocol: str | None = None


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness, so a dead host is told apart from a refused sentence."""
    return {"status": "ok", "simulated": "yes"}


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    """The host's one page: microphone, transcript and card."""
    return PAGE.read_text(encoding="utf-8")


@app.post("/say")
async def say(said: Said) -> Turn:
    """Route one sentence to one tool, and bring back everything the page renders.

    The idempotency key is made here, once per request. That is the honest boundary: a request
    retried by the page is one sale, while the same sentence spoken twice is two, which is what a
    counter does all day.
    """
    async with host.connect() as counter:
        spec = counter.protocol_version
        tools = await counter.tools()
        try:
            choice = await brain.choose(said.utterance, tools)
            arguments = brain.arguments(choice, said.utterance, uuid4().hex)
        except brain.Unclear as exc:
            return Turn(spoken=exc.question, ok=False, protocol=spec)
        except brain.UnknownTool:
            log.info("the chosen tool is not one this server offers")
            return Turn(
                spoken="I am not sure what to do with that. Could you say it again?",
                ok=False,
                protocol=spec,
            )

        tool = next(item for item in tools if item.name == choice.tool)
        answer = await counter.call(tool, arguments)

    log.info("turn finished with %s, ok=%s", tool.name, answer.ok)
    return Turn(
        spoken=answer.spoken,
        tool=tool.name,
        data=answer.data,
        card_html=answer.card_html,
        ok=answer.ok,
        protocol=spec,
    )
