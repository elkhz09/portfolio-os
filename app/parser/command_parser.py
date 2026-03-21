"""Strict Telegram command parser.

All commands must match a known schema exactly. Ambiguous or malformed
commands raise ParseError rather than guessing intent.
"""

import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CommandName(str, Enum):
    START = "start"        # welcome + guide
    STATUS = "status"
    POSITIONS = "positions"
    BUY = "buy"
    SELL = "sell"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    REBALANCE = "rebalance"
    JOURNAL = "journal"
    RISK = "risk"
    PNL = "pnl"
    WEIGHT = "weight"      # /weight TICKER 0.25
    HISTORY = "history"    # /history [TICKER]
    PRICE = "price"        # /price TICKER 185.50


class ParseError(ValueError):
    """Raised when a command cannot be parsed unambiguously."""


@dataclass
class ParsedCommand:
    name: CommandName
    args: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TICKER_RE = re.compile(r"^[A-Z]{1,10}$")
_POSITIVE_FLOAT_RE = re.compile(r"^\d+(\.\d+)?$")


def _require_ticker(value: str) -> str:
    if not _TICKER_RE.match(value.upper()):
        raise ParseError(f"Invalid ticker symbol: {value!r}")
    return value.upper()


def _require_positive_float(value: str, name: str) -> float:
    if not _POSITIVE_FLOAT_RE.match(value):
        raise ParseError(f"{name} must be a positive number, got: {value!r}")
    result = float(value)
    if result <= 0:
        raise ParseError(f"{name} must be > 0")
    return result


def _extract_thesis(tokens: list[str]) -> tuple[str | None, list[str]]:
    """Pull --thesis ... out of a token list. Everything after --thesis is the thesis.
    Returns (thesis, tokens_before_flag)."""
    try:
        idx = tokens.index("--thesis")
    except ValueError:
        return None, tokens
    if idx + 1 >= len(tokens):
        raise ParseError("--thesis flag requires a value")
    thesis = " ".join(tokens[idx + 1:])
    remaining = tokens[:idx]
    return thesis, remaining


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_command(text: str) -> ParsedCommand:
    """Parse a raw Telegram message into a ParsedCommand.

    Args:
        text: Raw message text, e.g. "/buy AAPL 100 --thesis 'bullish macro'".

    Returns:
        ParsedCommand with validated fields.

    Raises:
        ParseError: If the command is unknown, malformed, or ambiguous.
    """
    text = text.strip()
    # Normalize em dash (—) and en dash (–) to -- so mobile keyboards don't break flags
    text = text.replace("\u2014", "--").replace("\u2013", "--")
    if not text.startswith("/"):
        raise ParseError("Commands must start with '/'")

    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        raise ParseError(f"Could not tokenise command: {exc}") from exc

    raw_cmd = tokens[0].lstrip("/").lower()
    # Strip bot username suffix (e.g. /buy@mybot)
    raw_cmd = raw_cmd.split("@")[0]

    try:
        cmd = CommandName(raw_cmd)
    except ValueError:
        raise ParseError(f"Unknown command: /{raw_cmd}")

    args_tokens = tokens[1:]

    match cmd:
        case CommandName.START | CommandName.STATUS | CommandName.POSITIONS | CommandName.RISK | CommandName.PNL:
            if args_tokens:
                raise ParseError(f"/{cmd.value} takes no arguments")
            return ParsedCommand(name=cmd)

        case CommandName.BUY | CommandName.SELL:
            thesis, args_tokens = _extract_thesis(args_tokens)
            if len(args_tokens) < 2:
                raise ParseError(
                    f"Usage: /{cmd.value} TICKER SIZE [LIMIT_PRICE] [--thesis '...']"
                )
            ticker = _require_ticker(args_tokens[0])
            size = _require_positive_float(args_tokens[1], "SIZE")
            limit_price: float | None = None
            if len(args_tokens) == 3:
                limit_price = _require_positive_float(args_tokens[2], "LIMIT_PRICE")
            elif len(args_tokens) > 3:
                raise ParseError(f"Too many positional arguments for /{cmd.value}")
            return ParsedCommand(
                name=cmd,
                args={"ticker": ticker, "size": size, "limit_price": limit_price, "thesis": thesis},
            )

        case CommandName.CONFIRM | CommandName.CANCEL:
            if len(args_tokens) != 1:
                raise ParseError(f"Usage: /{cmd.value} ORDER_ID")
            try:
                order_id = int(args_tokens[0])
            except ValueError:
                raise ParseError(f"ORDER_ID must be an integer, got: {args_tokens[0]!r}")
            return ParsedCommand(name=cmd, args={"order_id": order_id})

        case CommandName.WEIGHT:
            if len(args_tokens) != 2:
                raise ParseError("Usage: /weight TICKER TARGET_WEIGHT  (e.g. /weight AAPL 0.25)")
            ticker = _require_ticker(args_tokens[0])
            try:
                weight = float(args_tokens[1])
            except ValueError:
                raise ParseError(f"TARGET_WEIGHT must be a number, got: {args_tokens[1]!r}")
            if not (0.0 < weight <= 1.0):
                raise ParseError(f"TARGET_WEIGHT must be in range (0, 1], got {weight}")
            return ParsedCommand(name=cmd, args={"ticker": ticker, "weight": weight})

        case CommandName.HISTORY:
            ticker: str | None = None
            if len(args_tokens) == 1:
                ticker = _require_ticker(args_tokens[0])
            elif args_tokens:
                raise ParseError("Usage: /history [TICKER]")
            return ParsedCommand(name=cmd, args={"ticker": ticker})

        case CommandName.PRICE:
            if len(args_tokens) != 2:
                raise ParseError("Usage: /price TICKER PRICE  (e.g. /price AAPL 185.50)")
            ticker = _require_ticker(args_tokens[0])
            try:
                price = float(args_tokens[1])
            except ValueError:
                raise ParseError(f"PRICE must be a number, got: {args_tokens[1]!r}")
            if price <= 0:
                raise ParseError(f"PRICE must be positive, got {price}")
            return ParsedCommand(name=cmd, args={"ticker": ticker, "price": price})

        case CommandName.REBALANCE:
            thesis, args_tokens = _extract_thesis(args_tokens)
            if args_tokens:
                raise ParseError("/rebalance takes no positional arguments")
            return ParsedCommand(name=cmd, args={"thesis": thesis})

        case CommandName.JOURNAL:
            # /journal                        -> list entries
            # /journal add TICKER note text   -> note with ticker
            # /journal add note text          -> note without ticker
            if not args_tokens:
                return ParsedCommand(name=cmd, args={"subcommand": "list"})
            if args_tokens[0].lower() == "add":
                remaining = args_tokens[1:]
                if not remaining:
                    raise ParseError("Usage: /journal add [TICKER] note")
                # If first token matches ticker pattern and more tokens follow, treat as ticker
                ticker = None
                if len(remaining) >= 2 and _TICKER_RE.match(remaining[0].upper()):
                    ticker = remaining[0].upper()
                    note = " ".join(remaining[1:])
                else:
                    note = " ".join(remaining)
                return ParsedCommand(
                    name=cmd,
                    args={"subcommand": "add", "ticker": ticker, "note": note},
                )
            raise ParseError("Unknown /journal subcommand. Try /journal or /journal add")

        case _:
            raise ParseError(f"Unhandled command: {cmd}")
