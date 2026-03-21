"""Strict Pydantic instruction schema for portfolio commands.

Each user action maps to a concrete, validated instruction model.
``parse_instruction`` converts a raw command string into one of these models,
raising ``InstructionError`` on any validation failure so that nothing ambiguous
ever reaches the execution layer.

Actions
-------
BUY           /buy TICKER SHARES [LIMIT_PRICE] [--thesis "..."]
SELL          /sell TICKER SHARES [LIMIT_PRICE] [--thesis "..."]
SET_WEIGHT    /weight TICKER TARGET  (target in (0, 1])
REBALANCE     /rebalance [--thesis "..."]
SHOW_PORTFOLIO /status  or  /portfolio
SHOW_HISTORY  /history [TICKER]
ADD_THESIS    /journal add [TICKER] "note"
"""

from __future__ import annotations

import re
import shlex
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Shared domain types and validators
# ---------------------------------------------------------------------------

_TICKER_RE = re.compile(r"^[A-Z]{1,10}$")


def _validate_ticker(value: str) -> str:
    """Normalise and validate a ticker symbol."""
    value = value.strip().upper()
    if not _TICKER_RE.match(value):
        raise ValueError(
            f"Ticker must be 1–10 uppercase letters, got {value!r}"
        )
    return value


def _validate_shares(value: float) -> float:
    """Ensure share count is strictly positive."""
    if value <= 0:
        raise ValueError(f"Share count must be > 0, got {value}")
    return value


def _validate_weight(value: float) -> float:
    """Ensure portfolio weight is in the range (0, 1]."""
    if not (0.0 < value <= 1.0):
        raise ValueError(
            f"Target weight must be in range (0, 1], got {value}"
        )
    return value


# ---------------------------------------------------------------------------
# Action enum
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    SET_WEIGHT = "set_weight"
    REBALANCE = "rebalance"
    SHOW_PORTFOLIO = "show_portfolio"
    SHOW_HISTORY = "show_history"
    ADD_THESIS = "add_thesis"


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------

class BaseInstruction(BaseModel):
    """Base for all portfolio instructions.

    All instructions are immutable once constructed so they can be safely
    passed between layers without mutation risk.
    """

    action: ActionType
    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Action-specific models
# ---------------------------------------------------------------------------

class BuyInstruction(BaseInstruction):
    """Buy a fixed number of shares of *ticker*.

    Attributes:
        ticker: Instrument symbol (1–10 uppercase letters).
        shares: Number of shares to buy (> 0).
        limit_price: Optional limit price. If omitted, treated as market order.
        thesis: Optional rationale string attached to this trade.
    """

    action: Literal[ActionType.BUY] = ActionType.BUY
    ticker: str
    shares: float
    limit_price: float | None = None
    thesis: str | None = None

    @field_validator("ticker", mode="before")
    @classmethod
    def check_ticker(cls, v: str) -> str:
        """Validate ticker format."""
        return _validate_ticker(v)

    @field_validator("shares", mode="before")
    @classmethod
    def check_shares(cls, v: float) -> float:
        """Validate share count."""
        return _validate_shares(float(v))

    @field_validator("limit_price", mode="before")
    @classmethod
    def check_limit_price(cls, v: float | None) -> float | None:
        """Validate limit price when provided."""
        if v is None:
            return None
        v = float(v)
        if v <= 0:
            raise ValueError(f"Limit price must be > 0, got {v}")
        return v


class SellInstruction(BaseInstruction):
    """Sell a fixed number of shares of *ticker*.

    Attributes:
        ticker: Instrument symbol.
        shares: Number of shares to sell (> 0).
        limit_price: Optional limit price.
        thesis: Optional rationale string.
    """

    action: Literal[ActionType.SELL] = ActionType.SELL
    ticker: str
    shares: float
    limit_price: float | None = None
    thesis: str | None = None

    @field_validator("ticker", mode="before")
    @classmethod
    def check_ticker(cls, v: str) -> str:
        return _validate_ticker(v)

    @field_validator("shares", mode="before")
    @classmethod
    def check_shares(cls, v: float) -> float:
        return _validate_shares(float(v))

    @field_validator("limit_price", mode="before")
    @classmethod
    def check_limit_price(cls, v: float | None) -> float | None:
        if v is None:
            return None
        v = float(v)
        if v <= 0:
            raise ValueError(f"Limit price must be > 0, got {v}")
        return v


class SetWeightInstruction(BaseInstruction):
    """Set a target portfolio weight for *ticker*.

    Attributes:
        ticker: Instrument symbol.
        target_weight: Desired fraction of portfolio value (0, 1].
    """

    action: Literal[ActionType.SET_WEIGHT] = ActionType.SET_WEIGHT
    ticker: str
    target_weight: float

    @field_validator("ticker", mode="before")
    @classmethod
    def check_ticker(cls, v: str) -> str:
        return _validate_ticker(v)

    @field_validator("target_weight", mode="before")
    @classmethod
    def check_weight(cls, v: float) -> float:
        return _validate_weight(float(v))


class RebalanceInstruction(BaseInstruction):
    """Rebalance the portfolio towards the current target weights.

    Attributes:
        thesis: Optional rationale for this rebalance event.
    """

    action: Literal[ActionType.REBALANCE] = ActionType.REBALANCE
    thesis: str | None = None


class ShowPortfolioInstruction(BaseInstruction):
    """Show the current portfolio state."""

    action: Literal[ActionType.SHOW_PORTFOLIO] = ActionType.SHOW_PORTFOLIO


class ShowHistoryInstruction(BaseInstruction):
    """Show trade history, optionally filtered to a single ticker.

    Attributes:
        ticker: If provided, filter to this instrument only.
    """

    action: Literal[ActionType.SHOW_HISTORY] = ActionType.SHOW_HISTORY
    ticker: str | None = None

    @field_validator("ticker", mode="before")
    @classmethod
    def check_ticker(cls, v: str | None) -> str | None:
        return _validate_ticker(v) if v is not None else None


class AddThesisInstruction(BaseInstruction):
    """Add a thesis note to the journal.

    Attributes:
        note: The thesis text (non-empty).
        ticker: If provided, attach the note to a specific instrument.
    """

    action: Literal[ActionType.ADD_THESIS] = ActionType.ADD_THESIS
    note: str
    ticker: str | None = None

    @field_validator("ticker", mode="before")
    @classmethod
    def check_ticker(cls, v: str | None) -> str | None:
        return _validate_ticker(v) if v is not None else None

    @field_validator("note", mode="before")
    @classmethod
    def check_note(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Thesis note must not be empty")
        return v

    @model_validator(mode="after")
    def check_not_empty(self) -> "AddThesisInstruction":
        if not self.note:
            raise ValueError("Thesis note must not be empty")
        return self


# ---------------------------------------------------------------------------
# Discriminated union — the single return type of parse_instruction
# ---------------------------------------------------------------------------

AnyInstruction = Annotated[
    Union[
        BuyInstruction,
        SellInstruction,
        SetWeightInstruction,
        RebalanceInstruction,
        ShowPortfolioInstruction,
        ShowHistoryInstruction,
        AddThesisInstruction,
    ],
    Field(discriminator="action"),
]


# ---------------------------------------------------------------------------
# Parse error
# ---------------------------------------------------------------------------

class InstructionError(ValueError):
    """Raised when a command string cannot be parsed into a valid instruction."""


# ---------------------------------------------------------------------------
# Tokenization helpers (self-contained — no coupling to command_parser internals)
# ---------------------------------------------------------------------------

def _tokenise(text: str) -> list[str]:
    try:
        return shlex.split(text.strip())
    except ValueError as exc:
        raise InstructionError(f"Could not tokenise command: {exc}") from exc


def _pop_thesis(tokens: list[str]) -> tuple[str | None, list[str]]:
    """Extract --thesis VALUE from token list. Returns (value, remaining)."""
    try:
        idx = tokens.index("--thesis")
    except ValueError:
        return None, tokens
    if idx + 1 >= len(tokens):
        raise InstructionError("--thesis flag requires a value")
    value = tokens[idx + 1]
    return value, tokens[:idx] + tokens[idx + 2:]


def _require_float(raw: str, name: str) -> float:
    try:
        v = float(raw)
    except ValueError:
        raise InstructionError(f"{name} must be a number, got {raw!r}")
    return v


# ---------------------------------------------------------------------------
# Public parse function
# ---------------------------------------------------------------------------

def parse_instruction(text: str) -> AnyInstruction:
    """Parse a raw command string into a typed, validated instruction model.

    Accepts the same ``/command args`` syntax used by the Telegram bot.

    Args:
        text: Raw command text, e.g. ``/buy AAPL 50 --thesis 'bullish macro'``.

    Returns:
        An ``AnyInstruction`` instance (one of the concrete instruction types).

    Raises:
        InstructionError: If the command is unknown, malformed, or fails
            field-level validation.
    """
    text = text.strip()
    if not text.startswith("/"):
        raise InstructionError("Commands must start with '/'")

    tokens = _tokenise(text)
    raw_cmd = tokens[0].lstrip("/").lower().split("@")[0]
    rest = tokens[1:]

    try:
        return _dispatch(raw_cmd, rest)
    except (InstructionError, ValueError) as exc:
        # Re-wrap Pydantic ValidationError strings that bubble up as ValueError
        raise InstructionError(str(exc)) from exc


def _dispatch(cmd: str, rest: list[str]) -> AnyInstruction:  # noqa: C901
    """Map a command name and token list to a concrete instruction."""

    match cmd:
        # ---- show portfolio ----
        case "status" | "portfolio" | "positions":
            if rest:
                raise InstructionError(f"/{cmd} takes no arguments")
            return ShowPortfolioInstruction()

        # ---- show history ----
        case "history":
            ticker: str | None = None
            if len(rest) == 1:
                ticker = rest[0]
            elif rest:
                raise InstructionError("Usage: /history [TICKER]")
            return ShowHistoryInstruction(ticker=ticker)

        # ---- buy ----
        case "buy":
            thesis, rest = _pop_thesis(rest)
            if len(rest) < 2:
                raise InstructionError(
                    "Usage: /buy TICKER SHARES [LIMIT_PRICE] [--thesis '...']"
                )
            if len(rest) > 3:
                raise InstructionError("Too many arguments for /buy")
            ticker_raw, shares_raw = rest[0], rest[1]
            limit_price = _require_float(rest[2], "LIMIT_PRICE") if len(rest) == 3 else None
            return BuyInstruction(
                ticker=ticker_raw,
                shares=_require_float(shares_raw, "SHARES"),
                limit_price=limit_price,
                thesis=thesis,
            )

        # ---- sell ----
        case "sell":
            thesis, rest = _pop_thesis(rest)
            if len(rest) < 2:
                raise InstructionError(
                    "Usage: /sell TICKER SHARES [LIMIT_PRICE] [--thesis '...']"
                )
            if len(rest) > 3:
                raise InstructionError("Too many arguments for /sell")
            ticker_raw, shares_raw = rest[0], rest[1]
            limit_price = _require_float(rest[2], "LIMIT_PRICE") if len(rest) == 3 else None
            return SellInstruction(
                ticker=ticker_raw,
                shares=_require_float(shares_raw, "SHARES"),
                limit_price=limit_price,
                thesis=thesis,
            )

        # ---- set target weight ----
        case "weight":
            if len(rest) != 2:
                raise InstructionError(
                    "Usage: /weight TICKER TARGET_WEIGHT  (e.g. /weight AAPL 0.25)"
                )
            return SetWeightInstruction(
                ticker=rest[0],
                target_weight=_require_float(rest[1], "TARGET_WEIGHT"),
            )

        # ---- rebalance ----
        case "rebalance":
            thesis, rest = _pop_thesis(rest)
            if rest:
                raise InstructionError("/rebalance takes no positional arguments")
            return RebalanceInstruction(thesis=thesis)

        # ---- journal / add thesis ----
        case "journal":
            if not rest:
                # /journal with no subcommand → treat as show history (thesis entries)
                return ShowHistoryInstruction(ticker=None)
            if rest[0].lower() != "add":
                raise InstructionError(
                    "Unknown /journal subcommand. Use /journal add [TICKER] 'note'"
                )
            rest = rest[1:]
            if not rest:
                raise InstructionError("Usage: /journal add [TICKER] 'note'")
            # Two forms: /journal add TICKER "note"  OR  /journal add "note"
            if len(rest) == 1:
                return AddThesisInstruction(note=rest[0], ticker=None)
            if len(rest) == 2:
                # Heuristic: first token is ticker if it matches ticker pattern
                if re.match(r"^[A-Za-z]{1,10}$", rest[0]):
                    return AddThesisInstruction(ticker=rest[0], note=rest[1])
                raise InstructionError(
                    f"Expected TICKER then note, got {rest[0]!r} {rest[1]!r}"
                )
            raise InstructionError("Usage: /journal add [TICKER] 'note'")

        case _:
            raise InstructionError(f"Unknown command: /{cmd}")
