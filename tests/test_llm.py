"""The single door to the model: drains a stream to text, and a structured stream to a value."""

import sys

import pytest
from pydantic import BaseModel, ValidationError
from strands.models import Model

from counter.agent import llm
from counter.config import Settings
from tests.fakes import FakeModel

NOVA_MICRO = "us.amazon.nova-micro-v1:0"
NOVA_LITE = "us.amazon.nova-lite-v1:0"


class Sale(BaseModel):
    """A sale parsed out of one spoken sentence."""

    item: str
    qty: int


def use_settings(monkeypatch, **overrides):
    """Pin settings so the developer's own .env cannot change a result."""
    monkeypatch.setattr(llm, "settings", lambda: Settings(_env_file=None, **overrides))


@pytest.fixture(autouse=True)
def clear_model_cache():
    llm._model.cache_clear()
    yield
    llm._model.cache_clear()


@pytest.fixture
def fake(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(llm, "_model", lambda smart=False: model)
    return model


async def test_complete_joins_the_text_deltas(fake):
    fake.text = "two kilos of sugar recorded"
    assert await llm.complete("anything") == "two kilos of sugar recorded"


async def test_complete_ignores_reasoning_deltas(fake):
    assert "thinking" not in await llm.complete("anything")


async def test_complete_passes_the_system_prompt_separately_from_the_utterance(fake):
    await llm.complete("do doodh aur ek bread", system="You record sales.")
    messages, system = fake.calls[0]
    assert system == "You record sales."
    assert messages == [{"role": "user", "content": [{"text": "do doodh aur ek bread"}]}]


async def test_parse_returns_a_validated_model(fake):
    fake.fields = {"item": "sugar", "qty": 2}
    got = await llm.parse("do kilo cheeni", Sale)
    assert isinstance(got, Sale)
    assert (got.item, got.qty) == ("sugar", 2)


async def test_parse_rejects_fields_that_break_the_schema(fake):
    fake.fields = {"item": "sugar", "qty": "a few"}
    with pytest.raises(ValidationError):
        await llm.parse("kuch cheeni", Sale)


def test_default_uses_the_fast_model_and_smart_uses_the_smart_one(monkeypatch):
    monkeypatch.setenv("AWS_CA_BUNDLE", "already-set")  # skip the cert dump; see counter/tls.py
    use_settings(monkeypatch)
    assert llm._model(False).get_config()["model_id"] == NOVA_MICRO
    assert llm._model(True).get_config()["model_id"] == NOVA_LITE


def test_an_unknown_provider_is_named_in_the_error(monkeypatch):
    use_settings(monkeypatch, llm_provider="ollama")
    with pytest.raises(llm.ProviderNotConfigured) as caught:
        llm._model(False)
    assert caught.value.provider == "ollama"
    assert "bedrock" in str(caught.value)


def test_groq_without_a_key_is_refused_before_any_network_call(monkeypatch):
    use_settings(monkeypatch, llm_provider="groq", groq_api_key="")
    with pytest.raises(llm.ProviderNotConfigured) as caught:
        llm._model(False)
    assert "GROQ_API_KEY" in str(caught.value)


async def test_the_model_is_built_once_per_size(monkeypatch):
    built = []

    def build(smart):
        built.append(smart)
        return FakeModel()

    use_settings(monkeypatch, llm_provider="counting")
    monkeypatch.setitem(llm._BUILDERS, "counting", build)
    await llm.complete("first")
    await llm.complete("second")
    assert built == [False]


def test_strands_is_the_provider_layer(monkeypatch):
    """Eligibility guard: Strands must be in the call path, not just in the README."""
    monkeypatch.setenv("AWS_CA_BUNDLE", "already-set")
    use_settings(monkeypatch)
    assert isinstance(llm._model(False), Model)
    assert issubclass(FakeModel, Model)


def test_groq_without_the_openai_extra_names_the_install_command(monkeypatch):
    """Hides the extra whether or not it is installed, so the test does not depend on the env."""
    monkeypatch.delitem(sys.modules, "strands.models.openai", raising=False)
    monkeypatch.setitem(sys.modules, "openai", None)
    use_settings(monkeypatch, llm_provider="groq", groq_api_key="present")
    with pytest.raises(llm.ProviderNotConfigured) as caught:
        llm._model(False)
    assert "strands-agents[openai]" in str(caught.value)


async def test_an_absurdly_long_prompt_is_refused_before_it_is_billed(fake):
    with pytest.raises(llm.PromptTooLong):
        await llm.complete("a" * (llm.MAX_PROMPT_CHARS + 1))
    assert fake.calls == []


async def test_a_reply_with_no_parsed_value_is_refused_rather_than_returned_as_none(fake, monkeypatch):
    async def no_output(output_model, prompt, system_prompt=None, **kwargs):
        yield {"chunk": "thinking"}

    monkeypatch.setattr(fake, "structured_output", no_output)
    with pytest.raises(llm.EmptyReply):
        await llm.parse("do kilo cheeni", Sale)


def test_secrets_are_masked_in_the_settings_repr():
    """A printed or logged Settings must not reveal the Neon password or an API key."""
    pinned = Settings(_env_file=None, database_url="postgres://u:hunter2@host/db", groq_api_key="gsk_live")
    printed = repr(pinned)
    assert "hunter2" not in printed
    assert "gsk_live" not in printed
    assert pinned.groq_api_key.get_secret_value() == "gsk_live"
