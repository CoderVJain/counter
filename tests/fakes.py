"""A scripted model, so tests exercise the real drain helpers with no network and no credentials."""

from collections.abc import AsyncGenerator
from typing import Any

from strands.models import Model
from strands.types.content import Messages


class FakeModel(Model):
    """Replays fixed replies and records what it was asked, so prompts can be asserted on."""

    def __init__(self, text: str = "ok", fields: dict[str, Any] | None = None):
        self.text = text
        self.fields = fields or {}
        self.calls: list[tuple[Messages, str | None]] = []

    def update_config(self, **model_config: Any) -> None:
        """Nothing to update."""

    def get_config(self) -> dict[str, Any]:
        """Enough for a test to tell which model it is holding."""
        return {"model_id": "fake"}

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs) -> AsyncGenerator:
        """Emit a reasoning delta first, then the text one word per delta, as Bedrock would."""
        self.calls.append((messages, system_prompt))
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockDelta": {"delta": {"reasoningContent": {"text": "thinking out loud"}}}}
        for word in self.text.split():
            yield {"contentBlockDelta": {"delta": {"text": word + " "}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs) -> AsyncGenerator:
        """Validate the scripted fields through the caller's model, exactly as a provider does."""
        self.calls.append((prompt, system_prompt))
        yield {"output": output_model(**self.fields)}


class ScriptedModel(FakeModel):
    """One fake for a turn that parses twice, scripted per output model.

    A whole voice turn asks the model two different questions - which tool the sentence means, then
    what the sale says - so one set of fields cannot answer both. Scripts are keyed on the class
    name being filled, and a class nobody scripted is an error rather than an empty answer.
    """

    def __init__(self, scripts: dict[str, dict[str, Any]], text: str = "ok"):
        super().__init__(text=text)
        self.scripts = scripts

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs) -> AsyncGenerator:
        """Answer as whichever model was asked for."""
        self.calls.append((prompt, system_prompt))
        name = output_model.__name__
        if name not in self.scripts:
            raise AssertionError(f"nothing scripted for {name}")
        yield {"output": output_model(**self.scripts[name])}
