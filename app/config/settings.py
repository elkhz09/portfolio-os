"""Application settings loaded from environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration. All values can be overridden via .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Bot
    telegram_bot_token: str = ""
    telegram_allowed_user_ids: list[int] = []

    # Database
    database_url: str = "sqlite:///./portfolio.db"

    # App behaviour
    paper_mode: bool = True
    log_level: str = "INFO"
    secret_key: str = "change-me"
    tradable_allowlist: set[str] = set()  # empty = allow all tickers

    # Optional market data
    alpha_vantage_api_key: str = ""
    polygon_api_key: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()
