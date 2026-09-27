"""Environment-backed settings. Loaded once, imported everywhere."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Values come from the environment or a local .env file.

    Credentials are SecretStr so that printing or logging this object, or a traceback that
    happens to hold it, cannot reveal them. Read one with .get_secret_value().
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr = SecretStr("")
    aws_region: str = "us-east-1"
    bedrock_model_fast: str = "us.amazon.nova-micro-v1:0"
    bedrock_model_smart: str = "us.amazon.nova-lite-v1:0"
    llm_provider: str = "bedrock"
    groq_api_key: SecretStr = SecretStr("")
    agentcore_memory_id: str = ""
    supplier_sim_url: str = "http://localhost:8100"
    # The address the server is reached on from outside, such as counter.onrender.com. The MCP SDK
    # refuses requests whose Host header it does not recognise, so a tunnelled demo needs this set.
    public_host: str = ""
    telegram_bot_token: SecretStr = SecretStr("")
    # The scheduled morning briefing. Off unless switched on, because it is the one thing here that
    # can call a model while nobody is watching. The hour and minute are shop time, not UTC.
    briefing_enabled: bool = False
    briefing_hour: int = 8
    briefing_minute: int = 0
    # Where sim_client reaches this server's MCP endpoint. The literal 127.0.0.1 is deliberate:
    # "localhost" resolves to ::1 first on Windows, uvicorn binds IPv4, and the refused attempt
    # costs about 1.2 seconds on every connection - measured 27 Sep, against 0.08 by address. The
    # host opens one connection per utterance, so that was dead air in the middle of the demo.
    counter_mcp_url: str = "http://127.0.0.1:8000/mcp"


@lru_cache
def settings() -> Settings:
    """Cached settings instance."""
    return Settings()
