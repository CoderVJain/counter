# Counter

A voice back-office for small shopkeepers, built as an MCP server. The shopkeeper's hands are busy, so sales,
stock, customer credit, supplier orders and the daily summary all run by voice.

> Counter is an entry in the Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ track). The Alexa+ MCP
> Toolkit is partner-gated, so the demo host is a simulated Alexa+ experience included in this repo. It is not
> affiliated with or endorsed by Amazon. Supplier ordering, payments and reminders are simulated and labelled
> as such.

## Status

Phases 0 to 4 are complete: the domain layer, the agent layer, the MCP server, the three MCP Apps cards, the
simulated Alexa+ host and the scheduled briefing. All eight tools are reachable over Streamable HTTP, and 289
tests pass without touching a model or a network. Evals, the public deployment and the submission are next.
See [plan.md](plan.md) for the phase plan.

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                  # install dependencies
uv run python -m counter.seed --reset    # build the demo shop in local SQLite
uv run pytest
```

`.env` is optional for now: local development runs on SQLite and AWS credentials come from `aws configure`.
Set `DATABASE_URL` to switch to Neon Postgres.

If your machine sits behind a TLS-inspecting proxy or antivirus, add `--native-tls` to uv commands or set
`UV_NATIVE_TLS=1`.

## Run

```bash
uv run uvicorn counter.server:app --reload --port 8000   # MCP server at /mcp
uv run uvicorn supplier_sim.app:app --port 8100          # simulated supplier
uv run uvicorn sim_client.app:app --port 8200            # the simulated Alexa+ host
npx @modelcontextprotocol/inspector                      # drive the tools at http://127.0.0.1:8000/mcp
```

The endpoint is `http://127.0.0.1:8000/mcp`, one address for POST and GET, and it negotiates MCP
**2025-11-25**. `/healthz` answers separately for the host we deploy to. Use the address rather than the name:
`localhost` resolves to `::1` first on Windows, uvicorn binds IPv4, and the refused attempt costs about a
second on every connection.

### The simulated Alexa+ host

Open `http://127.0.0.1:8200` with the MCP server running. Type a sentence or press **Speak** - the microphone
and the voice are the browser's own (`SpeechRecognition` and `speechSynthesis`), so they need no key and cost
nothing. Chrome asks for microphone permission the first time, and its dictation needs a network connection.

Things to say:

| Say | What happens |
|---|---|
| `do kilo cheeni Sharma ji ko, kal dega` | 2 kg of sugar leaves stock, Rs 90 goes on Sharma ji's credit, due tomorrow |
| `do doodh aur teen bread cash` | a two-item cash sale, each item taking the number spoken beside it |
| `good morning` | the briefing card: what has run low, what is due today, what to reorder |
| `how was today` | the daily summary card |
| `kitni cheeni bachi hai` | a stock check, spoken rather than drawn |

A turn costs one Bedrock call to choose the tool, plus whatever that tool needs - a sale is parsed, and most
tools have a sentence written for them to say. The tool choice and the parse are both cached on the sentence,
so repeating yourself is cheaper; only the spoken reply is written fresh. The host is for development and
must never be tunnelled - it has no authentication, and neither does the server it talks to.

### The scheduled briefing

Off unless it is switched on, because it is the only thing here that can call a model with nobody watching:

```bash
BRIEFING_ENABLED=true BRIEFING_HOUR=8 BRIEFING_MINUTE=0 uv run uvicorn counter.server:app --port 8000
```

It runs at most once per shop day and never retries a failed call.

### Reaching the MCP server from outside

Name the public address first, or the SDK will refuse every request that does not arrive from localhost:

```bash
PUBLIC_HOST=your-tunnel.trycloudflare.com uv run uvicorn counter.server:app --port 8000
cloudflared tunnel --url http://localhost:8000
```

### The demo has no authentication

There is no login on this server, and authentication is out of scope for the hackathon build. Anyone who can
reach the address can record a sale or place a simulated order. So: open a tunnel only while demonstrating,
close it afterwards, and do not publish the URL. Arguments are length-capped and amounts are bounded, which
limits what a stray request can cost, but that is a limit, not a door.

## Design

The LLM understands, code decides. Models only turn speech into structured intents and write short spoken
text; every quantity, price and balance is computed by deterministic code in `counter/domain/` and written
through an audit log. Stock is derived from an append-only movement table and can never go negative. Supplier
orders and outgoing reminders are two-step: draft, then explicit confirmation.

Two things follow from measuring the model rather than trusting it. **Quantities are read from the sentence,
not from the model.** Nova returns a confident wrong quantity once a sentence has extra words - "do kilo cheeni
Sharma ji ko, kal dega" comes back as one kilo rather than two, every time, while the customer and the due date
are correct - and a wrong quantity on a ledger is silent. So the number is taken from the words the shopkeeper
actually said, and anything still unaccounted for becomes a question rather than a write. **And every writing
tool takes an idempotency key**, so a retried request replays its first answer instead of selling twice.

The three cards are MCP Apps resources, rendered by the host in a sandboxed iframe with no `allow-same-origin`
and a CSP that grants no outbound origin. They render supplier notes and customer names, so they write text
with `textContent` and never as markup.

## License

MIT - see [LICENSE](LICENSE).
