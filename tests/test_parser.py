"""Tests for the strict command parser."""

import pytest

from app.parser.command_parser import CommandName, ParseError, ParsedCommand, parse_command


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_status():
    cmd = parse_command("/status")
    assert cmd.name == CommandName.STATUS
    assert cmd.args == {}


def test_buy_minimal():
    cmd = parse_command("/buy AAPL 50")
    assert cmd.name == CommandName.BUY
    assert cmd.args["ticker"] == "AAPL"
    assert cmd.args["size"] == 50.0
    assert cmd.args["limit_price"] is None
    assert cmd.args["thesis"] is None


def test_buy_with_price_and_thesis():
    cmd = parse_command("/buy MSFT 100 350.50 --thesis 'AI tailwind'")
    assert cmd.args["ticker"] == "MSFT"
    assert cmd.args["size"] == 100.0
    assert cmd.args["limit_price"] == 350.50
    assert cmd.args["thesis"] == "AI tailwind"


def test_sell():
    cmd = parse_command("/sell SPY 10 --thesis 'trimming risk'")
    assert cmd.name == CommandName.SELL
    assert cmd.args["ticker"] == "SPY"
    assert cmd.args["thesis"] == "trimming risk"


def test_confirm():
    cmd = parse_command("/confirm 42")
    assert cmd.name == CommandName.CONFIRM
    assert cmd.args["order_id"] == 42


def test_cancel():
    cmd = parse_command("/cancel 7")
    assert cmd.name == CommandName.CANCEL
    assert cmd.args["order_id"] == 7


def test_journal_list():
    cmd = parse_command("/journal")
    assert cmd.name == CommandName.JOURNAL
    assert cmd.args["subcommand"] == "list"


def test_journal_add():
    cmd = parse_command("/journal add AAPL 'mega cap quality'")
    assert cmd.args["subcommand"] == "add"
    assert cmd.args["ticker"] == "AAPL"
    assert cmd.args["note"] == "mega cap quality"


def test_bot_username_suffix_stripped():
    cmd = parse_command("/status@myportfoliobot")
    assert cmd.name == CommandName.STATUS


def test_pnl():
    cmd = parse_command("/pnl")
    assert cmd.name == CommandName.PNL


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_unknown_command():
    with pytest.raises(ParseError, match="Unknown command"):
        parse_command("/foobar")


def test_missing_slash():
    with pytest.raises(ParseError, match="must start with"):
        parse_command("buy AAPL 10")


def test_buy_missing_size():
    with pytest.raises(ParseError):
        parse_command("/buy AAPL")


def test_buy_invalid_ticker():
    with pytest.raises(ParseError, match="Invalid ticker"):
        parse_command("/buy aapl123 10")


def test_buy_negative_size():
    with pytest.raises(ParseError):
        parse_command("/buy AAPL -5")


def test_buy_zero_size():
    with pytest.raises(ParseError, match="> 0"):
        parse_command("/buy AAPL 0")


def test_sell_zero_size():
    with pytest.raises(ParseError, match="> 0"):
        parse_command("/sell AAPL 0")


def test_buy_zero_limit_price():
    with pytest.raises(ParseError, match="> 0"):
        parse_command("/buy AAPL 10 0")


def test_confirm_non_integer():
    with pytest.raises(ParseError, match="integer"):
        parse_command("/confirm abc")


def test_status_with_args():
    with pytest.raises(ParseError, match="no arguments"):
        parse_command("/status extra")


def test_thesis_flag_without_value():
    with pytest.raises(ParseError, match="--thesis flag requires"):
        parse_command("/buy AAPL 10 --thesis")


def test_package_reexports_only_the_live_parser():
    """``app.parser`` exposes the regex parser and nothing else.

    Pins the deletion of the unused Pydantic instruction layer: it was
    imported on every bot startup purely through this re-export.
    """
    import app.parser as pkg

    assert pkg.parse_command is parse_command
    assert pkg.ParseError is ParseError
    assert not hasattr(pkg, "parse_instruction")
    assert not hasattr(pkg, "BuyInstruction")
