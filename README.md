# Counter

A voice back-office for small shopkeepers, built as an MCP server. The shopkeeper's hands are busy, so sales,
stock, customer credit, supplier orders and the daily summary all run by voice.

> Counter is an entry in the Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ track). The Alexa+ MCP
> Toolkit is partner-gated, so the demo host is a simulated Alexa+ experience included in this repo. It is not
> affiliated with or endorsed by Amazon. Supplier ordering, payments and reminders are simulated and labelled
> as such.

## Status

Phases 0 to 3 are complete: the domain layer, the agent layer and the MCP server, with all eight tools
reachable over Streamable HTTP and 208 tests. Cards, the simulated Alexa+ host and the scheduled briefing
are next. See [plan.md](plan.md) for the phase plan.

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
npx @modelcontextprotocol/inspector                      # drive the tools at http://localhost:8000/mcp
```

The endpoint is `http://localhost:8000/mcp`, one address for POST and GET, and it negotiates MCP
**2025-11-25**. `/healthz` answers separately for the host we deploy to.

To reach it from outside, name the public address first, or the SDK will refuse every request that does not
arrive from localhost:

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

Two things follow from measuring the model rather than trusting it. Every spoken quantity is checked against
the words the shopkeeper actually said before anything is written, because Nova returned a confident wrong
quantity on sentences with extra words, and a wrong quantity on a ledger is silent. And every writing tool
takes an idempotency key, so a repeated sentence replays its first answer instead of selling twice.

## License

MIT - see [LICENSE](LICENSE).
