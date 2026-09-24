# Counter — build plan

## Context

Counter is a voice back-office for small
shopkeepers, entered in the **Build, Ship, Shape: Amazon Developer Hackathon** (Alexa+ track, plus the AWS Builder
and Open Source mini-challenges). Submission closes **Oct 23, 2026 12:00 PM PDT**; internal target **Oct 20**.
This plan turns `CLAUDE.md` into ordered, buildable phases, and corrects three assumptions in it that the
research contradicts.

### Research findings that change `CLAUDE.md`

1. **No Alexa+ simulator for us.** The Alexa+ MCP Toolkit, add-on registration and device simulator are
   partner-gated and **US-only**. `alexa-ai deploy` and "demo in the Alexa+ simulator" in `CLAUDE.md` are not
   achievable from India. The rules explicitly permit **"a simulated Alexa+ experience … built using any AI or
   agentic tool of their choice"**, requiring only source code plus a video that clearly shows the simulated
   experience. **Decision: we build our own simulator** (`sim_client/`) — it is also the strongest candidate for
   the Open Source mini-challenge. `CLAUDE.md` must be updated in Phase 0 so it stops asserting the gated path.
2. **MCP spec floor is 2025-11-25, and the SDK has moved past it.** The official Python SDK is now on the **v2**
   line supporting spec `2026-07-28` and all earlier revisions. Negotiating ≥ `2025-11-25` over Streamable HTTP
   satisfies the rule; we assert this with a test, not a README claim.
3. **Cards have a real standard now.** MCP Apps (SEP-1865, ext-apps spec `2026-01-26`) is Final: UI resources at
   `ui://…` with mime type `text/html;profile=mcp-app`, referenced from tool metadata. Build `ui/` against that,
   not a bespoke card format.

### Scope decisions (from the user)

- **Firm:** Strands Agents SDK, Neon Postgres, own simulator, supplier sim.
- **Stretch:** AgentCore Memory, Telegram reminders. AWS Builder evidence rests on Bedrock (Nova) + Strands.
- **Build order:** layer by layer — domain → agent → MCP → UI → demo.

---

## Where we are (updated Sep 24, 2026)

**Phase 0 complete** except the AWS credits form. **Phase 1 complete**, ahead of its Oct 3 target.
48 tests passing, `ruff` clean. Next session starts Phase 2 (the parser).

| Phase | State | Notes |
|---|---|---|
| 0 Foundations | done | credits form still to submit (closes Oct 21) |
| 1 Domain layer | done | schema, stock, ledger, idempotency, units, orders, seed |
| 2 Agent layer | next | blocked on a model provider, see below |
| 3 MCP server | not started | |
| 4 UI, simulator, jobs | not started | |
| 5 Evals, docs, submission | not started | |

### Open blocker: Bedrock invocation is gated

AWS allows this account to list Nova models but not to invoke them. `Converse` and `InvokeModel` both return
`ValidationException: Operation not allowed`, in `us-east-1` and `us-west-2`, for both the foundation model ids
and the `us.` inference profiles, while `ListFoundationModels`, `ListInferenceProfiles` and STS all succeed on
the same credentials. One call did succeed once in `us-west-2` and six identical calls immediately after it
failed, so the entitlement exists but is enforced inconsistently. This is a new-account hold tied to billing
history, not a configuration fault. A free Account-and-billing support case is the remedy. Full detail in
`docs/FRICTION_LOG.md` entry 4.

**Consequence:** none for the Alexa+ track, which requires no AWS service. It weakens the AWS Builder
mini-challenge only. Phase 2 proceeds behind the `agent/llm.py` provider interface with a fallback provider,
so Bedrock drops in later as one env var with no parser rewrite.

### Next session, in order

1. `agent/llm.py` - provider interface, fake provider for tests, Bedrock and fallback implementations.
2. `agent/parser.py` - utterance plus catalog to a validated Pydantic intent, clarify rather than guess.
3. Re-check Bedrock with `uv run --native-tls python -m scripts.check_bedrock`.

### Environment notes

- uv and any script making outbound TLS calls need `--native-tls` or `UV_NATIVE_TLS=1` on this machine.
  Avast re-signs HTTPS with a private CA; `counter/tls.py` handles it for AWS calls.
- AWS credentials live in `~/.aws/credentials` via `aws configure`, never in `.env`.
- Local dev runs on SQLite (`counter.db`). Neon is not connected yet; `DATABASE_URL` switches it.

---

## Phase 0 — Foundations (Sep 24–27)

Goal: repo runs, AWS answers, `CLAUDE.md` is truthful.

- `git init`, MIT `LICENSE`, `.gitignore`, `.env.example`, public GitHub repo with **license visible in About**.
- `uv init` on Python 3.12; add `mcp`, `fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `pydantic`,
  `strands-agents`, `boto3`, `httpx`, `pytest`, `ruff`. Pin versions; record resolved `mcp` version.
- AWS: account check, **budget alert ≤ $10**, request the **$150 credits** (form closes Oct 21), enable Nova
  Micro/Lite in `us-east-1`, and run one raw `boto3` `converse` call to prove access. Zero quota → flip
  `LLM_PROVIDER=groq`.
- Neon project + `DATABASE_URL`.
- Edit `CLAUDE.md`: replace the `alexa-ai` CLI / Alexa+ simulator path with the simulated-Alexa+ path; note the
  MCP Apps extension for `ui/`.
- Start `docs/FRICTION_LOG.md` and `docs/PRODUCT_FEEDBACK.md` now — both are judged, both are worthless if
  written from memory in week 4.

**Done when:** `uv run pytest` passes an empty suite, one Nova call returns text, Neon connects.

## Phase 1 — Domain layer (Sep 28–Oct 3)

Goal: every number Counter says is computed by tested code. No LLM imports in `domain/`.

- `domain/models.py` — SQLAlchemy 2.x: `shop`, `item` (aliases[], unit, price, reorder_level),
  `stock_movement` (append-only), `customer` (nicknames[]), `credit_entry`, `sale`/`sale_line`, `supplier`,
  `supplier_order`(+lines), `audit_log`, `idempotency_key`. Alembic baseline migration.
- `domain/inventory.py` — stock as a fold over `stock_movement`; days-of-stock from trailing sales;
  **negative stock rejected** with a structured error, never clamped.
- `domain/ledger.py` — credit balances, dues by date, payment application.
- `domain/orders.py` — draft → confirm state machine.
- `domain/idempotency.py` — one decorator/helper: same key returns the first result, never a second write.
- `counter/seed.py` — 1 shop, ~40 items with Hinglish aliases, ~10 customers, 2 suppliers.
- `tests/` — stock math, balances, idempotency replay, negative-stock guard, alias/nickname resolution.

**Done when:** tests cover every write path; `uv run python -m counter.seed` populates Neon.

## Phase 2 — Agent layer (Oct 4–8)

Goal: messy speech → validated JSON. The LLM never does arithmetic.

- `agent/llm.py` — one `complete(prompt, *, smart=False) -> str` interface over Strands/Bedrock; Groq fallback
  behind `LLM_PROVIDER`. **No provider SDK is imported anywhere else.** Explain the loop and trade-offs to Varun
  before writing it.
- `agent/parser.py` — utterance + catalog (item aliases, customer nicknames) → Pydantic intent model. Low
  confidence or missing fields → a `Clarification` result, never a guess. Cache on
  `hash(utterance + catalog_version)`.
- `agent/forecaster.py` — reorder suggestion from trailing movement; the model ranks/explains, code computes.
- `agent/summarizer.py` — 1–2 sentence voice-friendly text.
- `agent/prompts/` — supplier and customer text wrapped as **data, never instructions**.
- Tests use a fake `llm` provider so the suite is offline and free.

**Done when:** ~30 hand-written utterances parse correctly; Nova Micro is the default, Lite only where Micro fails.

## Phase 3 — MCP server (Oct 9–13)

Goal: the eight tools, spec-compliant, over Streamable HTTP.

- `counter/server.py` — FastAPI app with the MCP Streamable HTTP app mounted at `/mcp` (single endpoint, POST+GET).
  Known friction: mounting on an existing FastAPI app has rough edges in the SDK — if it fights us, serve the MCP
  Starlette app directly and mount FastAPI under it, and log the episode in the friction log.
- `tools/` — `sales.py`, `credit.py`, `stock.py`, `orders.py`, `summary.py`. Handlers stay thin: parse via
  `agent/`, decide via `domain/`, format via `summarizer`. Tool names/descriptions are written for an LLM host to
  choose from — they are part of the product.
- Every write tool takes an **idempotency key**; `draft_supplier_order` → `confirm_supplier_order` is two-step and
  cannot be collapsed.
- `supplier_sim/app:app` on :8100, responses labelled **simulated**.
- `tests/test_protocol.py` — connect a real MCP client, assert negotiated protocol ≥ `2025-11-25`, assert all eight
  tools listed. This is the eligibility test; it must be in CI.
- Verify with `npx @modelcontextprotocol/inspector` against `http://localhost:8000/mcp`.

**Done when:** Inspector drives a sale end-to-end and the protocol test passes.

## Phase 4 — UI, simulator, jobs (Oct 14–17)

- `ui/` — MCP Apps resources at `ui://counter/…`, mime `text/html;profile=mcp-app`, referenced from tool metadata:
  briefing card, low-stock list, order-confirm card, daily summary.
- `sim_client/` — the simulated Alexa+ experience: connects to `/mcp` over Streamable HTTP, lists tools, lets a
  Bedrock-backed "brain" pick a tool from a typed or spoken utterance, renders the card in a sandboxed iframe and
  speaks the text. Clearly labelled **"simulated Alexa+ experience — not affiliated with Amazon"**; no Alexa
  branding, no Amazon marks.
- `jobs/` — scheduled morning briefing (autonomous signal).
- **Stretch, in this order if time allows:** AgentCore Memory wrapper (`memory/`) for nicknames and shop habits;
  Telegram reminders. Each must earn its place in the 3-minute video.

**Done when:** a spoken-style sentence in `sim_client/` produces a card and a correct DB write.

## Phase 5 — Evals, docs, submission (Oct 18–20)

- `evals/utterances.jsonl` — 150+ messy commands (fillers, stumbles, Hinglish, wrong units, unknown items,
  ambiguous customers) with expected structured output; `evals/run.py` reports intent accuracy, field accuracy,
  clarification rate, **wrong-write rate (target 0)**, p50 latency. Table goes in the README.
- Deploy to Render; smoke-test the public HTTPS `/mcp`.
- **Open Source mini-challenge:** extract `mcp-voice-eval` (the runner from `evals/`, generalised to any MCP
  server) into its own repo with MIT license, README and tests. Decide by Oct 8 whether this or `sim_client/` is
  the entry — `sim_client/` is the fallback if time is short.
- `docs/ARCHITECTURE.md` + diagram; finish `PRODUCT_FEEDBACK.md` (Bedrock/Nova, Strands, AgentCore if used,
  Alexa+ docs — answer all five required questions) and `FRICTION_LOG.md`.
- Concise README: what it is, setup, run, eval table, simulated-components disclosure.
- Record the video: **< 3 min**, English, public YouTube, shows the simulated experience working. No third-party
  marks or licensed music.
- Submit **Oct 20**. Re-read the rules page before submitting; rules beat this file.

---

## Standing rules while building

- Small diffs, tests after each, no unrelated refactors.
- Before any non-trivial component (agent loop, parser, idempotency, MCP transport), explain approach and
  trade-offs to Varun first, then build in reviewable steps.
- When an Amazon/AWS tool causes trouble, propose a `docs/FRICTION_LOG.md` entry in the same turn.
- Out of scope (stop and flag if a task drifts there): real payments, real supplier APIs, GST invoices,
  multi-shop, auth, web dashboard, mobile app.

## Verification

- `uv run pytest` — domain math, idempotency, negative-stock guard, parser-on-fake-LLM, protocol version.
- `uv run ruff check . && uv run ruff format .`
- `npx @modelcontextprotocol/inspector` against `http://localhost:8000/mcp` — list tools, run a sale, read a card.
- `uv run python -m evals.run` — wrong-write rate must be 0 before recording the video.
- End-to-end: `sim_client/` utterance → tool call → Neon row → card + spoken text, against the deployed Render URL.
