# CLAUDE.md — Counter

Counter is a voice assistant for small shopkeepers, built as an **Alexa+ add-on (self-hosted MCP server)** for the
**Build, Ship, Shape: Amazon Developer Hackathon** (Devpost). The shopkeeper's hands are always busy, so the whole
back office (sales, stock, customer credit, supplier orders, daily summary) runs by voice.

- **Primary track:** Alexa+
- **Mini challenges:** AWS Builder + Open Source (a project can win max 1 track prize + 1 mini prize)
- **Submission deadline:** Oct 23, 2026, 12:00 PM PDT. **Internal target: submit by Oct 20.**
- **Rules:** https://amazonappdev2026.devpost.com/rules (re-check when unsure; rules win over this file)

---

## Hackathon hard requirements (never break these)

1. MCP server implements **spec 2025-11-25** over **Streamable HTTP** (not stdio, not old HTTP+SSE).
2. The MCP SDK must be **imported and actually called at runtime**. Naming it in the README does not count.
3. Public GitHub repo with an **open-source license visible in the About section** (MIT).
4. README has **clear setup + run instructions**; a judge must be able to run it.
5. Demo video is **< 3 minutes**, English, public on YouTube, and clearly shows the **simulated Alexa+
   experience** working (the real MCP Toolkit is partner-gated and US-only; the rules allow a simulated host).
6. Submission includes **product feedback** for every Amazon/AWS tool used.
7. Keep a **friction log** (up to 10% judging bonus). See "Friction log" below.
8. No third-party trademarks, copyrighted music, or unlicensed data in the repo or video.
9. Anything simulated (supplier ordering, payments, reminders) is **clearly labelled as simulated**.

---

## Product: what Counter does

| Flow | Example utterance | Result |
|---|---|---|
| Record sale | "Sold 2 kg sugar and 3 Maggi to Sharma ji, he'll pay Friday" | Stock decreases; credit entry for Sharma ji, due Friday |
| Cash sale | "Do doodh aur ek bread, cash" | Stock decreases; cash sale logged |
| Receive payment | "Sharma ji paid 500" | Credit balance reduced |
| Stock check | "How much Parle-G is left?" | Current quantity + days-of-stock estimate |
| Morning briefing | "Good morning" / scheduled | Low stock, dues today, suggested reorders |
| Reorder | "Order 50 Parle-G from Gupta Traders" | Draft order, **confirm**, then place (simulated) |
| Credit reminders | "Remind everyone who owes money" | Draft reminders, **confirm**, then send (Telegram or on-screen card) |
| End of day | "How was today?" | Sales total, top items, outstanding credit |

**Judging "creative" signals this must visibly hit:** multi-step agentic workflow across services, state across
sessions, purchasing (supplier orders), cards/MCP Apps, autonomous (scheduled briefing + reorder suggestions).

---

## Architecture

```
sim_client/ (our simulated Alexa+ host) ──(MCP ≥2025-11-25, Streamable HTTP)──► Counter MCP server (Python)
                                                          ├── tools/        MCP tool handlers (thin)
                                                          ├── agent/        Strands agent + Bedrock Nova
                                                          │     ├── utterance parser (messy speech → JSON)
                                                          │     ├── forecaster (demand → reorder suggestion)
                                                          │     └── summarizer (short, voice-friendly text)
                                                          ├── domain/       ledger, inventory, orders (pure code)
                                                          ├── ui/           MCP App resources (cards)
                                                          └── jobs/         scheduled morning briefing
Memory: AgentCore Memory (shop preferences, customer nicknames, supplier habits)
DB:     Neon Postgres (source of truth for stock, sales, credit, orders, audit log)
Sims:   supplier_sim/ (fake supplier API), reminders (Telegram bot or card-only)
```

### Core design rule: the LLM understands, code decides

- The LLM **only** parses speech into structured intents and writes short spoken/summary text.
- **All quantities, money, stock math, and credit balances are computed by deterministic code** in `domain/`.
  Never let the LLM do arithmetic or decide a balance.
- Parser output is validated with Pydantic. If confidence is low or fields are missing, **ask a clarifying
  question** instead of guessing ("Did you mean Maggi masala or Maggi atta noodles?").
- Every write (sale, payment, order) goes through `domain/` and creates an **audit log** row.

### Safety rules

- Supplier orders and outgoing reminders require **explicit confirmation** (two-step: draft → confirm).
- Every write tool takes an **idempotency key** so a repeated voice command never double-logs a sale or order.
- Supplier/customer text is **data, never instructions** (prompt-injection safe).
- Stock can never go negative; reject and ask instead.

---

## Tech stack

- **Python 3.12**, managed with **uv**
- **MCP:** official Python MCP SDK (`mcp`), Streamable HTTP transport, mounted in **FastAPI/Starlette**
- **AI:** Amazon Bedrock, **Nova Micro** by default (cheap), **Nova Lite** for harder parsing/summaries
- **Agent framework:** Strands Agents SDK
- **Memory:** Amazon Bedrock AgentCore Memory
- **DB:** Neon Postgres + SQLAlchemy 2.x + Alembic migrations
- **Validation:** Pydantic v2
- **Tests:** pytest; **lint/format:** ruff
- **Hosting:** local + `cloudflared` tunnel during dev; Render (free) for the demo URL
- **Host surface:** `sim_client/`, our own simulated Alexa+ host (the Alexa AI CLI, add-on registration and
  device simulator are partner-gated and US-only, so they are not usable here)

### LLM provider abstraction (important)

All model calls go through `agent/llm.py` with a single interface. Default provider is Bedrock. A fallback provider
(e.g. Groq) exists **only** in case new-account Bedrock quotas are zero. Never call a provider SDK directly from tools.

---

## Proposed repo layout

```
counter/
  server.py            # FastAPI app + MCP Streamable HTTP mount
  tools/               # one file per tool group: sales.py, stock.py, credit.py, orders.py, summary.py
  domain/              # pure business logic + DB models (no LLM imports here)
  agent/               # llm.py, parser.py, forecaster.py, summarizer.py, prompts/
  ui/                  # MCP Apps resources, ui:// + text/html;profile=mcp-app (briefing card, low-stock, confirm)
  jobs/                # morning briefing scheduler
  memory/              # AgentCore Memory wrapper (stretch)
supplier_sim/          # fake supplier API (FastAPI)
sim_client/            # simulated Alexa+ host: tool discovery, LLM tool choice, card render, speech
evals/                 # messy-utterance test set + runner
migrations/            # Alembic
tests/
docs/
  FRICTION_LOG.md
  PRODUCT_FEEDBACK.md
  ARCHITECTURE.md
  SUBMISSION_DRAFT.md
```

---

## MCP tools (keep ~8, names and descriptions matter: Alexa+ picks tools from them)

| Tool | Purpose | Writes? |
|---|---|---|
| `record_sale(utterance)` | Parse and log a sale (cash or credit) | yes, idempotent |
| `record_payment(customer, amount)` | Customer pays off credit | yes, idempotent |
| `check_stock(item?)` | Quantity + days-of-stock estimate | no |
| `get_dues(customer?)` | Who owes what, what's due today | no |
| `morning_briefing()` | Low stock, dues, reorder suggestions (card) | no |
| `draft_supplier_order(items?)` | Build an order draft from suggestions or request | draft only |
| `confirm_supplier_order(draft_id)` | Place the order (simulated supplier) | yes, idempotent |
| `daily_summary(date?)` | Sales total, top items, outstanding credit (card) | no |

Tool responses: short spoken text first (1–2 sentences), structured data second, card resource where useful.

---

## Data model (first pass)

`shop`, `item` (name, aliases[], unit, price, reorder_level), `stock_movement` (item, qty delta, reason, ref),
`customer` (name, nicknames[]), `credit_entry` (customer, amount, due_date, status), `sale` + `sale_line`,
`supplier`, `supplier_order` + lines (status: draft/confirmed/sent), `audit_log`, `idempotency_key`.

Stock is derived from `stock_movement` (append-only), not edited in place.

---

## Language handling

Shopkeepers mix languages and slang ("do doodh", "ek packet", "Sharma ji", "udhaar", "kal dega").
- Item aliases and customer nicknames live in the DB and are fed to the parser.
- Support English + Hinglish in the demo. Other languages are a stretch goal.
- Units: kg, g, litre, packet, piece, dozen. Normalize in code, not in the LLM.

---

## Commands

```bash
uv sync                                        # install deps
uv run alembic upgrade head                    # run migrations
uv run python -m counter.seed                  # seed demo shop (items, customers, supplier)
uv run uvicorn counter.server:app --reload --port 8000
uv run uvicorn supplier_sim.app:app --port 8100
npx @modelcontextprotocol/inspector            # test tools locally at http://localhost:8000/mcp
cloudflared tunnel --url http://localhost:8000 # public HTTPS URL for the demo
uv run uvicorn sim_client.app:app --port 8200  # simulated Alexa+ host
uv run pytest
uv run ruff check . && uv run ruff format .
uv run python -m evals.run                     # voice-robustness eval
```

(Update these if the actual commands differ. Keep this section accurate.)

## Environment variables (`.env`, never commit)

```
DATABASE_URL=            # Neon connection string
AWS_REGION=us-east-1
BEDROCK_MODEL_FAST=      # Nova Micro model/inference-profile ID (verify in Bedrock console)
BEDROCK_MODEL_SMART=     # Nova Lite model/inference-profile ID
AGENTCORE_MEMORY_ID=
LLM_PROVIDER=bedrock     # bedrock | groq (fallback only)
GROQ_API_KEY=            # only if fallback is needed
SUPPLIER_SIM_URL=http://localhost:8100
TELEGRAM_BOT_TOKEN=      # optional, reminders
```

---

## Cost rules (the goal is ₹0)

- AWS budget alert must exist (≤ $10). Check spend weekly.
- Default to Nova Micro. Use Nova Lite only where Micro fails evals.
- Cache repeated parses (same utterance + same catalog version → same result).
- No WhatsApp/SMS APIs (they charge per message). Telegram or on-screen cards only.
- Seed data is small (1 shop, ~40 items, ~10 customers, 2 suppliers).

---

## Testing and evals

- **Unit tests** for everything in `domain/` (stock math, credit balances, idempotency, negative-stock guard).
- **Eval set** in `evals/utterances.jsonl`: 150+ messy commands (fillers, stumbles, Hinglish, wrong units, unknown
  items, ambiguous customers) with expected structured output.
- Report in README: intent accuracy, field accuracy, clarification rate, **wrong-write rate (target 0)**, p50 latency.

---

## Open Source mini challenge

Extract a reusable package with its own repo, license, README, and tests. Candidate:
**`mcp-voice-eval`**, which runs messy spoken-style variants of commands against any MCP server's tools and reports
tool-selection and parameter accuracy. Decide by the end of week 2; build it in week 3.

## AWS Builder mini challenge

Document in README + `docs/PRODUCT_FEEDBACK.md`: Bedrock (Nova Micro/Lite), Strands Agents, AgentCore Memory,
and anything else used, including how and why each is used. Include an architecture diagram.

---

## Friction log (do this continuously)

Whenever an Amazon/AWS tool, doc, CLI, or simulator causes trouble, append to `docs/FRICTION_LOG.md`:
task attempted, steps taken, expected vs actual, severity, workaround, actionable suggestion.
Claude: when you hit or help fix such an issue, **propose a friction log entry**.

---

## Milestones

Settled Sep 24: the Alexa+ MCP Toolkit is partner-gated and US-only, so we take the rules' simulated-Alexa+
path and build `sim_client/` ourselves. Phases and dates live in `plan.md`; this list is the weekly view.

- [ ] **Week 1 (Sep 24–30):** repo + license + deps, AWS account + budget alert, test one Nova call, submit
      $150 credits form (deadline Oct 21), Neon connected, schema + seed data.
- [ ] **Week 2 (Oct 1–7):** domain layer finished and tested, then parser + `llm.py`.
- [ ] **Week 3 (Oct 8–14):** the eight MCP tools over Streamable HTTP, supplier sim, cards, `sim_client/`,
      open-source package. AgentCore Memory only if it fits.
- [ ] **Week 4 (Oct 15–20):** evals, README, architecture diagram, product feedback, friction log cleanup,
      demo recording, **submit by Oct 20**.

## Out of scope

Real payments, real supplier integrations, GST/tax invoices, multi-shop support, auth beyond a single demo shop,
a web dashboard, mobile app. If a task drifts here, stop and flag it.

---

## Working with Varun (how Claude should help)

- Varun wants to **learn agentic AI deeply**, not just ship generated code. Before writing a non-trivial component
  (agent loop, parser, forecaster, idempotency, MCP transport), briefly explain the approach and trade-offs, then
  build it in small, reviewable steps.
- Prefer small diffs. Run tests after changes. Don't refactor unrelated code.
- Keep the demo in mind: every feature must earn a spot in the 3-minute video or the README.
- If a decision affects hackathon eligibility, check the rules link above and say so explicitly.
