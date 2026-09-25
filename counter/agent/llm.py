"""The one door to the language model.

Tools and agents never touch a provider SDK. They ask for one of two things: a short piece of spoken
text, or a Pydantic value parsed out of speech. Both go through the Strands Agents SDK, so Bedrock
Nova is genuinely the runtime model rather than a name in a README, and a second provider is a
settings change instead of a code change.

Bedrock is the default and the intended path. Groq exists only because a new AWS account can have
zero Nova access, and when that happens the demo still has to run; it speaks Groq's
OpenAI-compatible endpoint, so it needs GROQ_API_KEY and no OpenAI account. Both are
strands.models.Model subclasses, so everything below has exactly one code path.

Nothing here remembers a result and nothing here does arithmetic. Prompt assembly and the parse
cache live a layer up, in parser.py and summarizer.py, which are the only things that know the
catalog version a cache key needs.

Two safety contracts hold here, because this is the only place they can be enforced for every
caller:

- `prompt` is the spoken utterance and is treated as data. Instructions belong in `system`. A
  caller that concatenates a customer name or a supplier reply into `system` has defeated this, so
  don't.
- Nothing in this module logs a prompt or a reply. Utterances carry customer names and debts, and
  this server's logs are not a place for them.
"""

from collections.abc import AsyncIterable, Callable
from functools import lru_cache
from typing import Any

from strands.models import BedrockModel, Model
from strands.types.content import Messages
from strands.types.streaming import StreamEvent

from counter.config import settings
from counter.tls import use_system_certs

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Groq serves strict JSON schema on only some models, and parse() depends on it. The llama-3.x
# models offer json_object only and fail here, so these two ids are a constraint, not a preference.
GROQ_MODEL_FAST = "openai/gpt-oss-20b"
GROQ_MODEL_SMART = "openai/gpt-oss-120b"

# Zero temperature is what makes a repeated parse genuinely repeatable, and what keeps eval numbers
# comparable between runs.
TEMPERATURE = 0.0

# Reasoning models spend this budget thinking before they emit anything, so a tight cap truncates
# the answer rather than shortening it: at 512 a two-item sale returned an empty generation and a
# 400. This is a runaway guard, not a length target - billing follows tokens actually produced.
MAX_TOKENS = 2048

# The MCP server is meant to be publicly reachable during the demo, and input tokens are billed.
# A real spoken command is a sentence; anything this long is a mistake or an attempt to run up the
# bill, and it is cheaper to refuse it here than to discover it on the invoice.
MAX_PROMPT_CHARS = 2000


class ProviderNotConfigured(Exception):
    """Raised before any network call when settings name a provider we cannot build."""

    def __init__(self, provider: str, reason: str):
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider}: {reason}")


class PromptTooLong(Exception):
    """Raised instead of paying for a prompt no shopkeeper would ever speak."""

    def __init__(self, length: int):
        self.length = length
        super().__init__(f"{length} chars, limit is {MAX_PROMPT_CHARS}")


class EmptyReply(Exception):
    """Raised when a provider returns no parsed value, so a failed parse can never become a write."""


def _bedrock(smart: bool) -> Model:
    """Bedrock Nova: Micro by default, Lite when a harder job asks for it."""
    cfg = settings()
    return BedrockModel(
        model_id=cfg.bedrock_model_smart if smart else cfg.bedrock_model_fast,
        region_name=cfg.aws_region,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )


def _groq(smart: bool) -> Model:
    """Groq over its OpenAI-compatible endpoint. The key check comes first so a missing key is named."""
    secret = settings().groq_api_key
    if not secret:
        raise ProviderNotConfigured("groq", "GROQ_API_KEY is empty")

    try:
        from strands.models import OpenAIModel  # only the fallback needs this extra
    except ImportError as exc:
        raise ProviderNotConfigured("groq", 'run: uv add "strands-agents[openai]"') from exc

    return OpenAIModel(
        client_args={"api_key": secret.get_secret_value(), "base_url": GROQ_BASE_URL},
        model_id=GROQ_MODEL_SMART if smart else GROQ_MODEL_FAST,
        params={"temperature": TEMPERATURE, "max_tokens": MAX_TOKENS},
    )


_BUILDERS: dict[str, Callable[[bool], Model]] = {"bedrock": _bedrock, "groq": _groq}


@lru_cache
def _model(smart: bool) -> Model:
    """The one model object for this size. Cached: a voice turn makes several calls."""
    provider = settings().llm_provider
    build = _BUILDERS.get(provider)
    if build is None:
        raise ProviderNotConfigured(provider, f"expected one of {sorted(_BUILDERS)}")
    use_system_certs()  # every provider talks HTTPS, and this machine re-signs it
    return build(smart)


def _user(prompt: str) -> Messages:
    """One user turn, size-checked. Instructions belong in the system prompt, never in here."""
    if len(prompt) > MAX_PROMPT_CHARS:
        raise PromptTooLong(len(prompt))
    return [{"role": "user", "content": [{"text": prompt}]}]


async def _join_text(events: AsyncIterable[StreamEvent]) -> str:
    """Concatenate a stream's text deltas, ignoring reasoning and tool-use blocks."""
    parts: list[str] = []
    async for event in events:
        delta = event.get("contentBlockDelta", {}).get("delta", {})
        if "text" in delta:
            parts.append(delta["text"])
    return "".join(parts).strip()


async def _final_output(events: AsyncIterable[dict[str, Any]]) -> Any:
    """Take the validated value off the one event that carries it.

    Bedrock streams many events before it; Groq yields only this one. Matching on the key rather
    than taking the last event works for both.
    """
    value = None
    async for event in events:
        if "output" in event:
            value = event["output"]
    if value is None:
        raise EmptyReply("the model returned no structured output")
    return value


async def complete(prompt: str, *, system: str | None = None, smart: bool = False) -> str:
    """Ask for one short piece of text. No tools, no history."""
    return await _join_text(_model(smart).stream(_user(prompt), system_prompt=system))


async def parse[T](prompt: str, out: type[T], *, system: str | None = None, smart: bool = False) -> T:
    """Fill `out` from the prompt and return it validated.

    Keeping the utterance in the user turn and the instructions in `system` is what makes spoken
    text data rather than instructions. Note that `out` is part of the prompt: its docstring becomes
    the tool description and each field's description becomes that field's schema description, so
    parse accuracy is largely decided by how the model class is written.
    """
    return await _final_output(_model(smart).structured_output(out, _user(prompt), system_prompt=system))
