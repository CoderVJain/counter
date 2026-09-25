"""Run the utterance set against the live parser and report what a judge would want to know.

    LLM_PROVIDER=groq uv run --native-tls python -m evals.run

The number that matters is wrong-write rate: a sentence that resolved to a sale, confidently, with
the wrong item, quantity, customer or credit flag. A clarification is never a wrong write - asking
is the correct outcome when the shop stocks two oils.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from counter.agent import parser
from counter.domain.db import session

CASES = Path(__file__).parent / "utterances.jsonl"

# The set is deliberately full of Hindi, and a Windows console is not UTF-8 by default, so printing a
# clarification about "sabun" would end the run with an encoding error two thirds of the way through.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Groq's free tier allows 8000 tokens per minute and a parse costs roughly a thousand, so the run
# is paced rather than retried. A throttled request is not a parser failure and should not look
# like one in the numbers.
PAUSE_SECONDS = 7.0


def _actual(sale) -> dict:
    return {
        "items": sorted([line.item.name, line.qty_base] for line in sale.lines),
        "customer": sale.customer.name if sale.customer else None,
        "credit": sale.is_credit,
    }


def _expected(case: dict) -> dict:
    return {
        "items": sorted([name, qty] for name, qty in case["items"]),
        "customer": case["customer"],
        "credit": case["credit"],
    }


async def main() -> None:
    load_dotenv()
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    correct = wrong = asked = asked_ok = errors = 0
    latencies: list[float] = []

    with session() as db:
        for index, case in enumerate(cases):
            if index:
                await asyncio.sleep(PAUSE_SECONDS)
            started = time.monotonic()
            try:
                sale = await parser.parse_sale(db, case["say"])
                latencies.append(time.monotonic() - started)
                if case.get("clarify"):
                    wrong += 1
                    print(f"  WRONG-WRITE  {case['say'][:48]:48} recorded a sale, should have asked")
                elif _actual(sale) == _expected(case):
                    correct += 1
                else:
                    wrong += 1
                    print(f"  WRONG-WRITE  {case['say'][:48]:48} {_actual(sale)} != {_expected(case)}")
            except parser.NeedsClarification as exc:
                latencies.append(time.monotonic() - started)
                asked += 1
                if case.get("clarify"):
                    asked_ok += 1
                else:
                    print(f"  asked        {case['say'][:48]:48} {exc.question}")
            except Exception as exc:  # a crash is worse than a wrong answer; surface it
                errors += 1
                print(f"  ERROR        {case['say'][:48]:48} {type(exc).__name__}: {exc}")

    total = len(cases)
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0
    print(f"\ncases            {total}")
    print(f"correct          {correct}")
    print(f"clarified        {asked}  ({asked_ok} of them correctly)")
    print(f"WRONG WRITES     {wrong}  <- must be 0")
    print(f"errors           {errors}")
    print(f"p50 latency      {p50:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
