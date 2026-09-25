# Phase 3 — the MCP server

## Why this phase matters

Phases 1 and 2 are finished, about two weeks ahead of the dates in `plan.md`. The shop's rules live
in `counter/domain/` and the language work in `counter/agent/`. There are 124 tests, all offline and
free to run. The last run of the 34 spoken commands in `evals/` recorded **no wrong writes and no
errors**, which is the bar `CLAUDE.md` sets.

What is missing is the part a judge actually connects to: **an MCP server**. Today nothing listens on
a port. Everything we have built is reachable only from a Python prompt.

Two of the hackathon's hard requirements land in this phase and nowhere else:

1. The MCP SDK must be **imported and actually called at runtime**. Naming it in the README does not
   count.
2. It must speak **spec 2025-11-25 over Streamable HTTP** — not stdio, not the older HTTP with SSE.

Neither needs AWS, so the Bedrock hold does not block any of this. Bedrock access is expected within
four to five days of 25 September; when it arrives it is one environment variable.

**Done when:** the MCP Inspector can drive a complete sale against `http://localhost:8000/mcp`, and
an automated test proves both the agreed protocol version and all eight tool names.

---

## Read this before writing any code

We have `mcp` version 2.1.1, which is a rewrite. The notes below come from reading the installed
source, not from memory. Following an older guide will waste a day.

| Older guides say | This version actually wants |
|---|---|
| `from mcp.server.fastmcp import FastMCP` | `from mcp.server import MCPServer`. The old path raises an error **on purpose**, pointing at the rename |
| `FastMCP(stateless_http=True, host=..., port=...)` | The constructor takes none of these. They belong to `streamable_http_app()` |
| The MCP app mounts as a sub-path | It is an exact match. `/mcp` only — no sub-paths, no trailing slash |
| Resource addresses are typed as URLs, so `ui://` fights you | They are plain strings here, so `ui://` simply works |
| Latest protocol is 2025-06-18 | `2025-11-25` is what a client agrees on; `2026-07-28` exists but is not reachable through the normal handshake |

### Three traps, each worth an afternoon

1. **The server will look dead unless we start its session manager.** FastAPI does not start a
   mounted application's background work for it. We must wrap our own startup with
   `async with mcp.session_manager.run():`, and we must build the MCP app *first*, because that call
   is what creates the manager.
2. **It will refuse every request through a tunnel unless we name our public address.** When the host
   is left as `127.0.0.1`, the SDK quietly switches on protection against disguised requests.
   Anything arriving through Cloudflare or Render carries a different address and is turned away.
   This will bite at the worst moment — the first time we show it to someone.
3. **Only one kind of error reaches the shopkeeper.** Raising the SDK's own `ToolError` passes our
   message to the host to read out. Any other exception has its message thrown away and replaced with
   a generic line, so a carefully worded "Did you mean mustard oil or refined oil?" would vanish.

### Two things we get for free

- **Cards are already supported.** The SDK ships MCP Apps in the box, with `ui://` addresses, the
  right content type, and a way to ask whether the connected host can show cards at all, so we can
  fall back to speech. That is Phase 4's work, but there is no plumbing to invent.
- **Short text and structured data travel together.** One reply can carry a spoken sentence and
  machine-readable data, which is exactly the shape `CLAUDE.md` asks for.

---

## What already exists, and must be reused

Tools stay thin. They understand with `agent/`, decide with `domain/`, and phrase with `summarizer`.
Nothing in `counter/tools/` should hold a business rule or do arithmetic.

| Need | Already built |
|---|---|
| Understand a spoken sale | `agent/parser.parse_sale(db, utterance)` |
| Spoken word to catalogue row | `domain/catalog.find_item`, `find_customer` |
| Spoken day to a date | `domain/dates.to_date`, `dates.spoken` |
| Quantity and money sums | `domain/units.*` |
| Stock levels and movements | `domain/inventory.on_hand`, `move`, `level`, `below_reorder_level` |
| Credit and payments | `domain/ledger.add_credit`, `record_payment`, `open_dues`, `due_by`, `outstanding_total` |
| Supplier orders | `domain/orders.suggest_reorder`, `create_draft`, `confirm`, `mark_sent`, `drafts` |
| Never write twice | `domain/idempotency.once(db, key, work)` |
| Spoken replies | `agent/summarizer.say`, `sale_recorded`; `agent/forecaster.explain` |

## Gaps to fill first

Three pieces do not exist yet. All three are plain code with no model involved.

- **`domain/sales.py`** — there is no way to write a sale. `seed.py:140` builds one inline for demo
  data, but nothing reusable exists. This module takes a parsed sale, writes the sale and its lines,
  records one stock movement per line, and adds a credit entry when the sale is on credit. It becomes
  the single write path for `record_sale`.
- **`domain/reports.py`** — `daily_summary` needs a day's takings, its best-selling items and the
  outstanding credit. Only `ledger.outstanding_total` exists today.
- **`supplier_sim/app.py`** — the folder holds an empty `__init__.py`. `config.supplier_sim_url` is
  defined but nothing calls it.

One constraint worth knowing early: `idempotency.once` stores whatever the work returns and replays
it later, so that value must be **plain data** — numbers, strings, lists and dictionaries. Handing it
a database row will fail when it tries to store it.

---

## The eight tools

Names and descriptions are part of the product, because the host picks a tool by reading them. Write
them for that reader.

| Tool | Writes? | Built from |
|---|---|---|
| `record_sale(utterance, idempotency_key)` | yes | `parser.parse_sale` → `sales.record` → `summarizer.sale_recorded` |
| `record_payment(customer, amount_rupees, idempotency_key)` | yes | `catalog.find_customer` → `ledger.record_payment` |
| `check_stock(item=None)` | no | `inventory.level`, `below_reorder_level` |
| `get_dues(customer=None)` | no | `ledger.open_dues`, `due_by`, `outstanding_total` |
| `morning_briefing()` | no | `below_reorder_level` + `orders.suggest_reorder` + `forecaster.explain` + `due_by` |
| `draft_supplier_order(items=None)` | draft only | `orders.suggest_reorder` → `orders.create_draft` |
| `confirm_supplier_order(draft_id, idempotency_key)` | yes | `orders.confirm` → supplier sim → `orders.mark_sent` |
| `daily_summary(date=None)` | no | `reports.*` |

Each returns **short spoken text first, structured data second**. The spoken text comes from
`summarizer`, which already falls back to plain facts when the model is unavailable, so a throttled
provider cannot break a tool.

## Two rules for every tool that writes

- **Saying it twice must not do it twice.** Speech gets repeated, networks retry, and a shopkeeper
  may repeat "sold 2 kg sugar" because they were not sure it heard. Every writing tool takes a key
  from the host and runs its work through `idempotency.once`, which does the work once and replays
  the same answer afterwards. Four kilos must never leave the shelf because one sentence was heard
  twice.
- **Anything that leaves the shop takes two steps.** `draft_supplier_order` and
  `confirm_supplier_order` stay separate and must not be merged. A draft is read back, a person
  agrees, and only then is the order placed. This is a rule in `CLAUDE.md`, not a preference.

## Asking instead of guessing

A question is **not** a failure. When the parser needs to ask, the tool returns the question as an
ordinary successful reply, so the host simply speaks it. The shopkeeper says a fuller sentence, and
we read that from scratch.

```
"ek litre oil"          ->  "Did you mean mustard oil or refined oil?"   (ordinary reply)
"mustard oil ek litre"  ->  sale recorded
```

**The server remembers nothing between turns.** Nothing can go stale, and an answer cannot be glued
onto the wrong sentence. Remembering the pending question would sound more natural, and it is what
"onboarding by use" needs later, but it is out of scope here — see the deferred section in `plan.md`.

Refusals from `domain/` are different. `InsufficientStock`, `UnitMismatch`, `Overpayment` and
`UnknownOrder` mean the shop's rules said no, so they are raised as the SDK's `ToolError`, which
hands our wording to the host. Anything a person should hear must travel by one of these two paths.
Never let a stack trace be the answer to "sold 2 kg sugar".

---

## How the server is put together

The order matters, for the reasons given above.

1. Build the MCP server object and register the eight tools on it.
2. Ask it for its web application, naming our public address so tunnelled requests are not refused,
   and choosing plain request-and-reply over a long-lived stream, because tunnels and free hosting
   often cut long connections.
3. Create the FastAPI application with a startup block that runs the MCP session manager.
4. Add a plain `/healthz` route, which Render needs.
5. Mount the MCP application **last**, because it claims anything not already matched.

The endpoint lands at `http://localhost:8000/mcp` — one address handling both POST and GET, which is
what "Streamable HTTP" means and what the rules require.

## Files

```
counter/server.py          FastAPI app, MCP mounted at /mcp
counter/tools/sales.py     record_sale, record_payment
counter/tools/stock.py     check_stock
counter/tools/credit.py    get_dues
counter/tools/orders.py    draft_supplier_order, confirm_supplier_order
counter/tools/summary.py   morning_briefing, daily_summary
counter/domain/sales.py    NEW - the one write path for a sale
counter/domain/reports.py  NEW - a day's takings and best sellers
supplier_sim/app.py        NEW - fake supplier, every reply labelled simulated
tests/test_protocol.py     the eligibility test
tests/test_tools_*.py      one file per tool group, offline
```

## Order of work

Finish and test each step before starting the next.

1. `domain/sales.py` and `domain/reports.py`, with tests. No server involved, so this is quick.
2. `counter/server.py` with **one** tool, `check_stock`, because it neither writes nor needs a model.
   Prove the whole path with the Inspector before anything else is built on it.
3. `record_sale`, the hardest one: understand, ask or record, protect against repeats.
4. The remaining five tools.
5. `supplier_sim`, then connect `confirm_supplier_order` to it.
6. `tests/test_protocol.py`, the eligibility test.

Step 2 is deliberately small. If the transport misbehaves, let it misbehave on the simplest possible
tool, not while we are also debugging a sale.

---

## Verification

1. `uv run pytest` — existing tests plus the new tool tests, offline, using `tests/fakes.py`.
2. `uv run ruff check . && uv run ruff format .`
3. `uv run uvicorn counter.server:app --reload --port 8000` and
   `uv run uvicorn supplier_sim.app:app --port 8100`.
4. `npx @modelcontextprotocol/inspector` against `http://localhost:8000/mcp` — list the tools, record
   a sale, check the stock fell, confirm an order.
5. `tests/test_protocol.py` connects a real MCP client and asserts the agreed protocol is 2025-11-25
   or later and that all eight tools are listed. **This is the eligibility test and it must run in
   CI.**

   Worth knowing: the existing `tests/test_protocol_version.py` only checks a constant in the
   library, which is a weaker claim than it looks. The library's "latest" is `2026-07-28`, but a
   client actually agrees on `2025-11-25`. The new test must assert what a **real session** settled
   on. The library also offers a proper comparison helper, which is safer than comparing dates as
   text.
6. `LLM_PROVIDER=groq uv run --native-tls python -m evals.run` still reports zero wrong writes.

## Security check for this phase

Per the standing rule in `plan.md`. This is the first time the shop's data is reachable from the
internet, so it deserves more care than the last two phases.

- **Everything is public.** Once the tunnel is open, anyone with the address can record a sale or
  place an order. There is no login, and `CLAUDE.md` puts authentication out of scope. Write the
  decision down: open the tunnel only while demonstrating, never publish the address, and say plainly
  in the README that the demo has no authentication.
- **Do not weaken the address check to make the tunnel work.** The tempting fix is to switch the
  protection off. The correct fix is to name our public address.
- **Bound every argument.** The spoken sentence is already capped, but amounts, dates, identifiers
  and item names each need a sensible limit. The SDK caps a whole request at 4 MB, which is far too
  generous for a shop command.
- **Supplier replies are outside text** and must be wrapped with `prompts.as_data` before any model
  sees them. This is the injection path that helper was written for.
- **No tool may log a sentence, a customer's name or an amount.** Log identifiers and counts.
- **Only plain data may be stored by the repeat protection**, because it keeps the result and replays
  it later.
- **Money arrives in rupees and is stored in paise.** That conversion belongs in one place, and a
  negative or absurd amount must be refused rather than recorded.

## Two small fixes to carry in

- The 25 September eval showed the model saying `"agla hafte"` where `dates.RELATIVE_PHRASES` lists
  only `"agle hafte"`, which caused an unnecessary question. One extra entry fixes it.
- Ghee is seeded as a liquid, so "ek kilo ghee" is refused. That refusal is correct for the data we
  have, but real shops sell ghee by weight too. Decide before the video is recorded.

## What this phase does not include

Cards, the simulated Alexa+ front end, and the scheduled morning briefing are all Phase 4. The
onboarding flow stays deferred. If a task starts drifting into those, stop and flag it.
