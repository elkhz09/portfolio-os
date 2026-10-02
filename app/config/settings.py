"""Application settings loaded from environment variables."""

import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration. All values can be overridden via .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Bot
    telegram_bot_token: str = ""
    telegram_allowed_user_ids: Annotated[list[int], NoDecode] = []

    # Database
    database_url: str = "sqlite:///./portfolio.db"

    # App behaviour
    paper_mode: bool = True
    log_level: str = "INFO"
    secret_key: str = "change-me"
    tradable_allowlist: Annotated[set[str], NoDecode] = set()  # empty = allow all tickers

    # Optional market data
    alpha_vantage_api_key: str = ""
    polygon_api_key: str = ""

    @field_validator("telegram_allowed_user_ids", "tradable_allowlist", mode="before")
    @classmethod
    def _split_comma_separated(cls, value):
        """Accept comma-separated strings for list/set fields.

        Both fields are documented as comma-separated. pydantic-settings would
        otherwise JSON-decode them in the source layer, before any validator runs,
        so ``AAPL,SPY`` raises a SettingsError and a bare ``123`` parses as an int.
        ``NoDecode`` on the annotations turns that decoding off and hands us the raw
        string here. JSON is still accepted so existing .env files keep working.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith(("[", "{")):
            # NoDecode turned off the automatic JSON parse, so do it here to keep
            # JSON-style .env files working.
            return json.loads(text)
        return [item.strip() for item in text.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()
