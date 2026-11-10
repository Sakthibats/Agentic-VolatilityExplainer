from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env from the project root regardless of CWD
_ENV_FILE = Path(__file__).parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    fred_api_key: SecretStr = SecretStr("")
    finnhub_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    # Which vendor runs the agent loop and the ticker-resolution fallback in query/parsing:
    # "anthropic" or "openai". The model is that vendor's *_model below. The eval harness
    # ignores this and builds each provider it compares directly (llm.build_provider).
    llm_provider: str = "anthropic"
    anthropic_model: str = "claude-haiku-5-5"
    openai_model: str = "gpt-6-luna"
    # How much an OpenAI reasoning model thinks before each turn: none | low | medium | high.
    openai_reasoning_effort: str = "low"
    supabase_url: SecretStr = SecretStr("")
    supabase_key: SecretStr = SecretStr("")
    redis_url: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
