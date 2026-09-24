"""Environment-backed settings. Loaded once, imported everywhere."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Values come from the environment or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""
    aws_region: str = "us-east-1"
    bedrock_model_fast: str = "us.amazon.nova-micro-v1:0"
    bedrock_model_smart: str = "us.amazon.nova-lite-v1:0"
    llm_provider: str = "bedrock"
    groq_api_key: str = ""
    agentcore_memory_id: str = ""
    supplier_sim_url: str = "http://localhost:8100"
    telegram_bot_token: str = ""


@lru_cache
def settings() -> Settings:
    """Cached settings instance."""
    return Settings()
