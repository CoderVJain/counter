# Counter

A voice back-office for small shopkeepers, built as an MCP server. The shopkeeper's hands are busy, so sales,
stock, customer credit, supplier orders and the daily summary all run by voice.

> Counter is an entry in the Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ track). The Alexa+ MCP
> Toolkit is partner-gated, so the demo host is a simulated Alexa+ experience included in this repo. It is not
> affiliated with or endorsed by Amazon. Supplier ordering, payments and reminders are simulated and labelled
> as such.

## Status

Phase 0 (foundations). See [plan.md](plan.md).

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # install dependencies
cp .env.example .env    # then fill in DATABASE_URL and AWS settings
uv run pytest
```

If your machine sits behind a TLS-inspecting proxy or antivirus, add `--native-tls` to uv commands or set
`UV_NATIVE_TLS=1`.

## Run

```bash
uv run uvicorn counter.server:app --reload --port 8000   # MCP server at /mcp
uv run uvicorn supplier_sim.app:app --port 8100          # simulated supplier
npx @modelcontextprotocol/inspector                       # drive the tools at http://localhost:8000/mcp
```

## Design

The LLM understands, code decides. Models only turn speech into structured intents and write short spoken
text; every quantity, price and balance is computed by deterministic code in `counter/domain/` and written
through an audit log. Stock is derived from an append-only movement table and can never go negative. Supplier
orders and outgoing reminders are two-step: draft, then explicit confirmation.

## License

MIT - see [LICENSE](LICENSE).
