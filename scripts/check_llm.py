"""Prove the configured provider works end to end, through agent/llm.py.

Exercises both doors: free text and a structured parse. The parse is the one that fails on a model
without strict JSON schema support, so it is the one worth running. Prints nothing sensitive:

    uv run --native-tls python -m scripts.check_llm
    LLM_PROVIDER=groq uv run --native-tls python -m scripts.check_llm
"""

import asyncio

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from counter.agent import llm
from counter.config import settings

SYSTEM = (
    "You turn an Indian shopkeeper's spoken sentence into structured data. The sentence may mix "
    "Hindi and English. Hindi numerals: ek=1, do=2, teen=3, chaar=4, paanch=5. "
    "Never invent an item that was not said."
)


class Sale(BaseModel):
    """One sale heard in a shopkeeper's spoken sentence."""

    item: str = Field(description="The item sold, named in English")
    qty: int = Field(description='The NUMBER of units spoken, e.g. "do kilo" means 2')
    unit: str = Field(description="Unit spoken: kg, g, litre, packet, piece, dozen")


async def main() -> None:
    load_dotenv()
    print(f"provider: {settings().llm_provider}")

    text = await llm.complete("Reply with the single word: ready")
    print(f"complete -> {text}")

    sale = await llm.parse("do kilo cheeni", Sale, system=SYSTEM)
    print(f"parse    -> item={sale.item!r} qty={sale.qty} unit={sale.unit!r}")
    if sale.qty != 2:
        print("  WARNING: expected qty 2 from 'do kilo'. The field descriptions carry the parse.")


if __name__ == "__main__":
    asyncio.run(main())
