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

## Where we are (updated Sep 25, 2026)

**Phase 0 complete**; the AWS credits form is submitted and awaiting a reply. **Phase 1 complete**, ahead of
its Oct 3 target. **Phase 2 complete.** `agent/` holds `llm.py`, `parser.py`, `summarizer.py`, `forecaster.py` and
`prompts.py`; `domain/` gained `catalog.py` and `dates.py`. 121 tests passing, `ruff` clean, and
`evals/` runs 34 utterances against the live model.
Next up is `agent/parser.py`.

| Phase | State | Notes |
|---|---|---|
| 0 Foundations | done | credits form submitted, no confirmation email yet as of Sep 25 |
| 1 Domain layer | done | schema, stock, ledger, idempotency, units, orders, seed |
| 2 Agent layer | done | all modules built; eval set run end to end on Groq with 0 wrong writes |
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

## Security check: run this at the end of every step

A shop's ledger holds names, debts and a payment history, and the demo server is publicly reachable
over a tunnel. So security is a per-step checklist, not a Phase 5 task. Before calling any step done,
walk these seven and note the answer in the commit message. Most steps touch only two or three.

1. **Secrets.** Does anything new hold a credential? It belongs in `Settings` as `SecretStr`, read with
   `.get_secret_value()` at the single point of use. Never in `.env.example`, a docstring, a test
   fixture, a log line, or the friction log.
2. **Logs and prints.** Does the new code log an utterance, a customer name, an amount, or a reply?
   Voice text is personal data. Log identifiers and counts, never content.
3. **Untrusted text.** Supplier replies, customer nicknames and item aliases are data. They go in the
   user turn or a tool result, never into a system prompt or an instruction string.
4. **Money and stock.** Can a failure return a partial or empty value that a later step treats as
   real? Refuse loudly instead. A silent `None` is how a wrong write happens.
5. **Cost.** Can an outsider make this call the model repeatedly, or with a huge input? Bound it. A
   public endpoint plus per-token billing is a denial-of-wallet risk.
6. **Writes.** Is every write idempotent, audit-logged, and impossible to trigger without the
   confirmation `CLAUDE.md` demands?
7. **Dependency.** Did this step add a package? Note why, and whether it brings network access or
   credentials it did not need before.

### Findings so far

| Step | Finding | Resolution |
|---|---|---|
| 2.1 `llm.py` | `repr(Settings())` printed the Neon password and Groq key in plaintext, so any log line or traceback could leak them | `database_url`, `groq_api_key`, `telegram_bot_token` are now `SecretStr`; two call sites unwrap explicitly |
| 2.1 `llm.py` | `parse()` returned `None` when a provider yielded no value, which a write path would have consumed as real | raises `EmptyReply` |
| 2.1 `llm.py` | no bound on prompt size, and the demo URL is public, so an outsider could run up the model bill | `MAX_PROMPT_CHARS = 2000`, enforced in `_user()` so no caller can bypass it |
| 2.1 `llm.py` | `use_system_certs()` ran only for Bedrock, so the Groq path failed TLS on this machine | moved into `_model()`, which covers every provider |
| 2.2 `parser.py` | **12x overcharge.** On 1 run in 3 the model returned `qty=12, unit=dozen` for "ek dozen", and code multiplied by 12 again: Rs 214 became Rs 1138 | the `qty` field description now forbids pre-multiplying; 0/6 on re-measure, plus a regression test |
| 2.2 `parser.py` | the model returned `qty='ek'` and `qty='1'` for the same sentence at temperature 0, so quantities were not reproducible | Hindi whole numbers moved into `units.QUANTITY_WORDS`, where the answer is the same every time |
| 2.2 `parser.py` | a model flag alone decided whether a sale was a debt, and "he will pay Friday" came back `is_credit=False` | `resolve()` derives credit from a stated payment day, so the flag cannot lose a debt |
| 2.2 `parser.py` | catalog text reaching the prompt would be an injection path | the catalog is never sent to the model; resolution happens in `catalog.py` against the database |
| 2.2 `parser.py` | *accepted risk:* clarification messages and `catalog` exceptions carry customer names, so logging them would put names in logs | no logging in these modules; the "log identifiers, never content" rule covers callers |
| 2.3 `dates.py` | computing "today" from `models.now()` (UTC) would misdate every debt taken after 18:30 UTC, because that is already tomorrow in India | `dates.today()` uses `SHOP_TZ = Asia/Kolkata`; a test pins it |
| 2.3 `dates.py` | a mis-heard day could otherwise land a debt in the past, i.e. born overdue or silently ignored | every phrase is read forwards, so no spoken day can resolve earlier than today |
| 2.4 `summarizer.py` | a model writing spoken text could state a figure code never computed, and a shopkeeper told the wrong balance stops trusting the till | every number in the generated sentence is checked against the facts it was given; `NumberInvented` otherwise, and `sale_recorded` falls back to the plain facts |
| 2.4 `forecaster.py` | a model ranking reorder urgency would spend the shop's cash on slow movers | ranking is code, by days of stock, with never-sold items sorted last rather than first. The model only writes the sentence |
| 2.5 `prompts.py` | **the prompt told the model to convert number words to digits while `units.py` already did it in code.** The model's copy won and was sometimes wrong: "bees" (20) came back as 22, an intermittent wrong write that spot checks pass | the prompt now says copy the quantity exactly as spoken and never convert. Same root cause as the deterministic 400 on "pav kilo jeera"; both clear |
| 2.5 `units.py` | "saath" (60) differs from "saat" (7) by one aspirated consonant, an eightfold error on a rare quantity | 60 is deliberately absent from the table, so it asks instead of guessing |
| 2.4 `prompts.py` | supplier and customer text concatenated into an instruction is the main injection path in Phase 3 | `as_data()` fences and labels outside text and neutralises a fence-break attempt; tested |
| 2.3 `dates.py` | the due phrase comes straight from the utterance | resolved by lookup table in code, never sent to a model. No new dependency: `zoneinfo` is stdlib |
| 2.2 `llm.py` | `MAX_TOKENS` 512 -> 2048 raises the worst-case cost per call about fourfold | accepted: 512 truncated reasoning models mid-JSON. Billing follows tokens produced, and `MAX_PROMPT_CHARS` still bounds input |

### Next session, in order

1. ~~`agent/llm.py`~~ done. `complete()` and `parse()` over Strands; Bedrock and Groq builders;
   `FakeModel` in `tests/fakes.py`. Design notes in `phase2-plan.md`.
2. ~~`agent/parser.py`~~ done, with `domain/catalog.py` underneath it for alias resolution.
   Confirmed: the intent model *is* the prompt. Both accuracy bugs above were fixed by rewriting a
   `Field(description=...)`, not by changing the model or the code.
3. ~~Due dates~~ done. `domain/dates.py` resolves "kal", "agle hafte", "somvar", "Friday" to a real
   date in shop time; `ParsedSale.due_date` now feeds straight into `ledger.add_credit(due_date=...)`.
   **Open judgment call:** a weekday said on its own weekday means a week out, on the grounds that
   someone paying today would say "aaj". On a Friday, "he'll pay Friday" therefore dates to next
   Friday. If that is wrong the debt is chased a week late, so put both readings in the eval set.
4. ~~`agent/summarizer.py`, `agent/forecaster.py`, `agent/prompts.py`~~ done, plus the parse cache
   and `evals/` (34 utterances, `LLM_PROVIDER=groq uv run --native-tls python -m evals.run`).
5. **Next: Phase 3, the MCP server.** `server.py` mounting Streamable HTTP, then the eight tools.
   `record_sale` is mostly wiring now: `parser.parse_sale` returns a `ParsedSale` whose lines feed
   `inventory.move` and whose credit feeds `ledger.add_credit(due_date=...)`, all behind
   `idempotency.once`.
6. Re-check Bedrock with `uv run --native-tls python -m scripts.check_bedrock`.

### Known, recorded rather than fixed

- **Ghee is seeded in litres**, so "ek kilo ghee" raises `UnitMismatch` and the assistant asks. That
  is the right refusal for the data we have, but ghee is genuinely sold both ways; decide whether the
  seed should carry a weight-based unit before the video.
- **Groq's free tier is 8000 tokens per minute**, which the eval run exceeds if unpaced. `evals/run.py`
  sleeps between cases for that reason. Not a parser property; do not read a throttle as a failure.
  Worth remembering *why* the pacing matters: the first, unpaced run reported **0 wrong writes and was
  wrong**. Throttling errored before the model could answer, so a real correctness bug looked like an
  infrastructure blip. An eval that is rate limited is not an eval.
- The **weekday-on-its-own-weekday** reading is still an assumption, see item 3.

**The Groq fallback works.** `strands-agents[openai]` is installed and `GROQ_API_KEY` is set, so
`LLM_PROVIDER=groq uv run --native-tls python -m scripts.check_llm` returns a real parse. Groq needs a
free Groq key, *not* an OpenAI one; the `openai` package is only an HTTP client pointed at Groq's
OpenAI-compatible endpoint. Keep the model ids pinned to `openai/gpt-oss-*` - Groq's llama-3.x models
serve `json_object` only and would fail `parse()`.

**Evidence for the parser, measured not guessed.** `do kilo cheeni` parsed as `qty=1` against a two-field
model, and as `qty=2` once the model gained a `unit` field and a description saying `"do kilo" means 2` -
on the *fast* model both times. So field descriptions carry the parse, not the model size. The fast model
also returned `unit='kilo'` where the smart one returned `'kg'`, which is why unit normalisation stays in
`domain/units.py` rather than in the prompt.

### Environment notes

- uv and any script making outbound TLS calls need `--native-tls` or `UV_NATIVE_TLS=1` on this machine.
  Avast re-signs HTTPS with a private CA; `counter/tls.py` handles it for AWS calls.
- AWS credentials live in `~/.aws/credentials` via `aws configure`, never in `.env`.
- Local dev runs on SQLite (`counter.db`). Neon is not connected yet; `DATABASE_URL` switches it.
  Three tiers: tests use in-memory `sqlite://` (`tests/conftest.py`), dev uses the `counter.db` file
  (`db.DEFAULT_URL`), Neon is whatever `DATABASE_URL` holds. See `.env.example` for the exact Neon
  string - the scheme must become `postgresql+psycopg://`, since psycopg2 is not installed.

  **Two known SQLite-to-Postgres differences, measured Sep 25:**

  1. `DateTime(timezone=True)` does **not** round-trip on SQLite. A value written as
     `datetime.now(UTC)` reads back with `tzinfo=None`, so `now() - row.created_at` raises
     `TypeError: can't subtract offset-naive and offset-aware datetimes`. On Neon the same row reads
     back aware and the subtraction works. No current code hits this - `inventory.py:54` subtracts
     before the query, not after - but the forecaster, `daily_summary` and `morning_briefing` all
     compare times, so **compare in SQL or normalise on read**, never subtract a value straight out
     of the DB.
  2. Money is integer paise and array-ish fields use the generic `JSON` type, so both are portable.
     That was the right call and should stay: `Numeric`/`Float` money and `postgresql.ARRAY` are the
     two things that would not have survived the switch.

  **No Alembic yet.** `migrations/` and `alembic.ini` do not exist; the schema is built by
  `Base.metadata.create_all()` in `seed.py` and `conftest.py`. So the `alembic upgrade head` line in
  `CLAUDE.md` Commands does not currently work. For one demo shop with no upgrade path, `create_all`
  against Neon is probably enough - decide in Phase 5 whether Alembic earns its place or the
  `CLAUDE.md` line should go.

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

## Deferred: onboarding-by-use (post-hackathon, design settled Sep 25)

Today the catalog, prices, customers and opening stock all come from `counter/seed.py`. For the
hackathon that is fine, reframed in the README as a **starter catalog** rather than demo data. The
real product cannot ship that way, and a judge may reasonably ask where the data came from.

**The answer is not a setup screen or a dashboard.** A wizard for 500 SKUs is the thing nobody
finishes, and it contradicts the premise that the shopkeeper's hands are busy. Instead the shop
builds itself through ordinary use: every unknown word is an onboarding moment, and the prompts for
it are already written at `parser.py:110` and `parser.py:134`.

- **Customers cost nothing.** "Sharma ji ko udhaar" already raises `UnknownCustomer` and asks
  "Add them?". One "haan" creates the row. Nicknames self-populate from however he actually says
  the name next time.
- **Items cost one question**, because a sale needs a price: "What do you sell it by, and for how
  much?" -> "kilo, pentalis rupaye". The spoken word ("cheeni") is stored as an alias for free, so
  nobody ever types an alias list, and `base_unit`/`base_per_unit` derive from the unit via
  `units.BASE_FACTORS`.
- **Stock in** needs the receipt path that `orders.py` deliberately left out: confirming a supplier
  order never increases stock, so today stock only ever falls. `inventory.move(db, item, +qty,
  "purchase", ref=order)` closes that loop.

**What it needs that does not exist yet:** somewhere to hold a pending clarification between turns
("I asked about cheeni; the price is in the next sentence"), plus the two-step confirm that
`CLAUDE.md` requires before any write. It needs **no new MCP tool** - it lives inside `record_sale`'s
clarification path, so the tool count stays at eight.

**Why it is worth doing eventually:** it turns the weakest part of the demo into the strongest. Day
one empty, one sentence creates item, customer and sale, then "the same shop a week later" for the
briefing and reorder flows. That also demonstrates state across sessions, which is one of the
judging signals. Roughly a session of work against about fifteen seconds of video.

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
