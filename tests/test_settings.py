"""Settings parsing tests.

Every case here loads through the environment rather than constructor kwargs.
That matters: pydantic-settings JSON-decodes complex fields inside the env source,
before any validator runs, so a bug at that layer is invisible to a test that
passes values straight to ``Settings(...)``. Both list-valued fields are declared
with ``NoDecode`` to switch that decoding off; these tests are what proves it.
"""

import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def build(monkeypatch, **env):
    """Load Settings from the environment, ignoring any real .env on disk."""
    for key in ("TELEGRAM_ALLOWED_USER_IDS", "TRADABLE_ALLOWLIST"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_comma_separated_user_ids(monkeypatch):
    settings = build(monkeypatch, TELEGRAM_ALLOWED_USER_IDS="123,987")
    assert settings.telegram_allowed_user_ids == [123, 987]


def test_single_user_id_without_brackets(monkeypatch):
    """The value shipped in .env.example. Used to abort startup as an int, not a list."""
    settings = build(monkeypatch, TELEGRAM_ALLOWED_USER_IDS="123456789")
    assert settings.telegram_allowed_user_ids == [123456789]


def test_comma_separated_allowlist(monkeypatch):
    """Documented in .env.example as TRADABLE_ALLOWLIST=AAPL,SPY,GLD."""
    settings = build(monkeypatch, TRADABLE_ALLOWLIST="AAPL,SPY,GLD")
    assert settings.tradable_allowlist == {"AAPL", "SPY", "GLD"}


def test_whitespace_and_trailing_commas_are_tolerated(monkeypatch):
    settings = build(monkeypatch, TELEGRAM_ALLOWED_USER_IDS=" 5 , 6 ,")
    assert settings.telegram_allowed_user_ids == [5, 6]


def test_json_form_still_accepted(monkeypatch):
    """JSON was the only form that worked before NoDecode; it must keep working."""
    settings = build(
        monkeypatch,
        TELEGRAM_ALLOWED_USER_IDS="[1,2]",
        TRADABLE_ALLOWLIST='["AAPL","SPY"]',
    )
    assert settings.telegram_allowed_user_ids == [1, 2]
    assert settings.tradable_allowlist == {"AAPL", "SPY"}


def test_empty_value_means_empty_collection(monkeypatch):
    settings = build(monkeypatch, TELEGRAM_ALLOWED_USER_IDS="", TRADABLE_ALLOWLIST="")
    assert settings.telegram_allowed_user_ids == []
    assert settings.tradable_allowlist == set()


def test_defaults_are_permissive_but_paper_mode_is_on(monkeypatch):
    settings = build(monkeypatch)
    assert settings.telegram_allowed_user_ids == []
    assert settings.tradable_allowlist == set()
    assert settings.paper_mode is True


@pytest.mark.parametrize("bad", ["abc", "1,abc", "[1,"])
def test_non_numeric_user_ids_are_rejected(monkeypatch, bad):
    with pytest.raises(ValidationError):
        build(monkeypatch, TELEGRAM_ALLOWED_USER_IDS=bad)
