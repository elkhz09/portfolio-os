"""Tests for the Pydantic instruction schema and parse_instruction."""

import pytest
from pydantic import ValidationError

from app.parser.instructions import (
    ActionType,
    AddThesisInstruction,
    BuyInstruction,
    InstructionError,
    RebalanceInstruction,
    SellInstruction,
    SetWeightInstruction,
    ShowHistoryInstruction,
    ShowPortfolioInstruction,
    parse_instruction,
)


# ===========================================================================
# Model-level validation tests (direct construction)
# ===========================================================================

class TestBuyInstructionModel:
    def test_valid(self):
        inst = BuyInstruction(ticker="AAPL", shares=10.0)
        assert inst.ticker == "AAPL"
        assert inst.shares == 10.0
        assert inst.action == ActionType.BUY
        assert inst.limit_price is None
        assert inst.thesis is None

    def test_ticker_normalised_to_uppercase(self):
        inst = BuyInstruction(ticker="aapl", shares=1.0)
        assert inst.ticker == "AAPL"

    def test_with_limit_and_thesis(self):
        inst = BuyInstruction(ticker="SPY", shares=5, limit_price=450.0, thesis="macro hedge")
        assert inst.limit_price == 450.0
        assert inst.thesis == "macro hedge"

    def test_zero_shares_invalid(self):
        with pytest.raises(ValidationError, match="Share count must be > 0"):
            BuyInstruction(ticker="AAPL", shares=0)

    def test_negative_shares_invalid(self):
        with pytest.raises(ValidationError, match="Share count must be > 0"):
            BuyInstruction(ticker="AAPL", shares=-1)

    def test_ticker_with_digits_invalid(self):
        with pytest.raises(ValidationError, match="1–10 uppercase letters"):
            BuyInstruction(ticker="AAP1", shares=10)

    def test_ticker_too_long_invalid(self):
        with pytest.raises(ValidationError, match="1–10 uppercase letters"):
            BuyInstruction(ticker="TOOLONGNAME", shares=10)

    def test_empty_ticker_invalid(self):
        with pytest.raises(ValidationError):
            BuyInstruction(ticker="", shares=10)

    def test_negative_limit_price_invalid(self):
        with pytest.raises(ValidationError, match="Limit price must be > 0"):
            BuyInstruction(ticker="AAPL", shares=10, limit_price=-1.0)

    def test_zero_limit_price_invalid(self):
        with pytest.raises(ValidationError, match="Limit price must be > 0"):
            BuyInstruction(ticker="AAPL", shares=10, limit_price=0.0)

    def test_immutable(self):
        inst = BuyInstruction(ticker="AAPL", shares=10)
        with pytest.raises(ValidationError):
            inst.shares = 20  # type: ignore[misc]


class TestSellInstructionModel:
    def test_valid(self):
        inst = SellInstruction(ticker="MSFT", shares=3.5)
        assert inst.action == ActionType.SELL
        assert inst.shares == 3.5

    def test_fractional_shares_valid(self):
        inst = SellInstruction(ticker="BRK", shares=0.001)
        assert inst.shares == pytest.approx(0.001)

    def test_zero_shares_invalid(self):
        with pytest.raises(ValidationError, match="Share count must be > 0"):
            SellInstruction(ticker="MSFT", shares=0)


class TestSetWeightInstructionModel:
    def test_valid_weight(self):
        inst = SetWeightInstruction(ticker="AAPL", target_weight=0.25)
        assert inst.target_weight == pytest.approx(0.25)

    def test_full_weight_allowed(self):
        inst = SetWeightInstruction(ticker="GLD", target_weight=1.0)
        assert inst.target_weight == 1.0

    def test_weight_zero_invalid(self):
        with pytest.raises(ValidationError, match="range \\(0, 1\\]"):
            SetWeightInstruction(ticker="AAPL", target_weight=0.0)

    def test_weight_above_one_invalid(self):
        with pytest.raises(ValidationError, match="range \\(0, 1\\]"):
            SetWeightInstruction(ticker="AAPL", target_weight=1.01)

    def test_weight_negative_invalid(self):
        with pytest.raises(ValidationError, match="range \\(0, 1\\]"):
            SetWeightInstruction(ticker="AAPL", target_weight=-0.1)


class TestAddThesisInstructionModel:
    def test_valid_with_ticker(self):
        inst = AddThesisInstruction(ticker="GLD", note="inflation hedge")
        assert inst.ticker == "GLD"
        assert inst.note == "inflation hedge"

    def test_valid_without_ticker(self):
        inst = AddThesisInstruction(note="general macro view")
        assert inst.ticker is None

    def test_empty_note_invalid(self):
        with pytest.raises(ValidationError, match="must not be empty"):
            AddThesisInstruction(note="")

    def test_whitespace_only_note_invalid(self):
        with pytest.raises(ValidationError, match="must not be empty"):
            AddThesisInstruction(note="   ")


# ===========================================================================
# parse_instruction — valid commands
# ===========================================================================

class TestParseInstructionBuy:
    def test_minimal(self):
        inst = parse_instruction("/buy AAPL 50")
        assert isinstance(inst, BuyInstruction)
        assert inst.ticker == "AAPL"
        assert inst.shares == 50.0
        assert inst.limit_price is None

    def test_with_limit_price(self):
        inst = parse_instruction("/buy MSFT 100 350.50")
        assert isinstance(inst, BuyInstruction)
        assert inst.limit_price == pytest.approx(350.50)

    def test_with_thesis(self):
        inst = parse_instruction("/buy NVDA 20 --thesis 'AI supercycle'")
        assert inst.thesis == "AI supercycle"

    def test_with_price_and_thesis(self):
        inst = parse_instruction("/buy SPY 10 500.00 --thesis 'index exposure'")
        assert inst.shares == 10.0
        assert inst.limit_price == pytest.approx(500.0)
        assert inst.thesis == "index exposure"

    def test_lowercase_ticker_normalised(self):
        inst = parse_instruction("/buy tsla 5")
        assert inst.ticker == "TSLA"

    def test_bot_suffix_stripped(self):
        inst = parse_instruction("/buy@portfoliobot AAPL 10")
        assert isinstance(inst, BuyInstruction)

    def test_fractional_shares(self):
        inst = parse_instruction("/buy BTC 0.5")
        assert inst.shares == pytest.approx(0.5)


class TestParseInstructionSell:
    def test_minimal(self):
        inst = parse_instruction("/sell AAPL 10")
        assert isinstance(inst, SellInstruction)
        assert inst.ticker == "AAPL"

    def test_with_thesis(self):
        inst = parse_instruction("/sell GLD 5 --thesis 'trimming'")
        assert inst.thesis == "trimming"

    def test_with_limit(self):
        inst = parse_instruction("/sell SPY 3 450.00")
        assert inst.limit_price == pytest.approx(450.0)


class TestParseInstructionSetWeight:
    def test_valid(self):
        inst = parse_instruction("/weight AAPL 0.25")
        assert isinstance(inst, SetWeightInstruction)
        assert inst.ticker == "AAPL"
        assert inst.target_weight == pytest.approx(0.25)

    def test_full_weight(self):
        inst = parse_instruction("/weight GLD 1.0")
        assert inst.target_weight == 1.0

    def test_small_weight(self):
        inst = parse_instruction("/weight TLT 0.05")
        assert inst.target_weight == pytest.approx(0.05)


class TestParseInstructionRebalance:
    def test_minimal(self):
        inst = parse_instruction("/rebalance")
        assert isinstance(inst, RebalanceInstruction)
        assert inst.thesis is None

    def test_with_thesis(self):
        inst = parse_instruction("/rebalance --thesis 'Q2 macro shift'")
        assert isinstance(inst, RebalanceInstruction)
        assert inst.thesis == "Q2 macro shift"


class TestParseInstructionShowPortfolio:
    def test_status(self):
        inst = parse_instruction("/status")
        assert isinstance(inst, ShowPortfolioInstruction)

    def test_portfolio_alias(self):
        inst = parse_instruction("/portfolio")
        assert isinstance(inst, ShowPortfolioInstruction)

    def test_positions_alias(self):
        inst = parse_instruction("/positions")
        assert isinstance(inst, ShowPortfolioInstruction)


class TestParseInstructionShowHistory:
    def test_without_ticker(self):
        inst = parse_instruction("/history")
        assert isinstance(inst, ShowHistoryInstruction)
        assert inst.ticker is None

    def test_with_ticker(self):
        inst = parse_instruction("/history AAPL")
        assert isinstance(inst, ShowHistoryInstruction)
        assert inst.ticker == "AAPL"


class TestParseInstructionAddThesis:
    def test_with_ticker_and_note(self):
        inst = parse_instruction("/journal add AAPL 'quality compounder'")
        assert isinstance(inst, AddThesisInstruction)
        assert inst.ticker == "AAPL"
        assert inst.note == "quality compounder"

    def test_without_ticker(self):
        inst = parse_instruction("/journal add 'general macro thesis'")
        assert isinstance(inst, AddThesisInstruction)
        assert inst.ticker is None
        assert inst.note == "general macro thesis"

    def test_journal_no_subcommand_returns_history(self):
        inst = parse_instruction("/journal")
        assert isinstance(inst, ShowHistoryInstruction)


# ===========================================================================
# parse_instruction — invalid commands
# ===========================================================================

class TestParseInstructionErrors:
    def test_missing_slash(self):
        with pytest.raises(InstructionError, match="must start with"):
            parse_instruction("buy AAPL 10")

    def test_unknown_command(self):
        with pytest.raises(InstructionError, match="Unknown command"):
            parse_instruction("/foobar")

    def test_buy_missing_shares(self):
        with pytest.raises(InstructionError):
            parse_instruction("/buy AAPL")

    def test_buy_zero_shares(self):
        with pytest.raises(InstructionError):
            parse_instruction("/buy AAPL 0")

    def test_buy_negative_shares(self):
        with pytest.raises(InstructionError):
            parse_instruction("/buy AAPL -5")

    def test_buy_invalid_ticker(self):
        with pytest.raises(InstructionError):
            parse_instruction("/buy AAPL123 10")

    def test_buy_too_many_args(self):
        with pytest.raises(InstructionError, match="Too many arguments"):
            parse_instruction("/buy AAPL 10 100 200")

    def test_buy_non_numeric_shares(self):
        with pytest.raises(InstructionError):
            parse_instruction("/buy AAPL lots")

    def test_sell_zero_shares(self):
        with pytest.raises(InstructionError):
            parse_instruction("/sell MSFT 0")

    def test_weight_zero(self):
        with pytest.raises(InstructionError):
            parse_instruction("/weight AAPL 0")

    def test_weight_above_one(self):
        with pytest.raises(InstructionError):
            parse_instruction("/weight AAPL 1.5")

    def test_weight_missing_args(self):
        with pytest.raises(InstructionError):
            parse_instruction("/weight AAPL")

    def test_weight_non_numeric(self):
        with pytest.raises(InstructionError):
            parse_instruction("/weight AAPL heavy")

    def test_status_with_args(self):
        with pytest.raises(InstructionError, match="no arguments"):
            parse_instruction("/status extra")

    def test_history_too_many_args(self):
        with pytest.raises(InstructionError):
            parse_instruction("/history AAPL MSFT")

    def test_history_invalid_ticker(self):
        with pytest.raises(InstructionError):
            parse_instruction("/history AAPL123")

    def test_rebalance_with_positional_args(self):
        with pytest.raises(InstructionError, match="no positional arguments"):
            parse_instruction("/rebalance NOW")

    def test_thesis_flag_without_value(self):
        with pytest.raises(InstructionError, match="--thesis flag requires"):
            parse_instruction("/buy AAPL 10 --thesis")

    def test_journal_unknown_subcommand(self):
        with pytest.raises(InstructionError, match="Unknown /journal subcommand"):
            parse_instruction("/journal delete 1")

    def test_journal_add_empty_note(self):
        with pytest.raises(InstructionError):
            parse_instruction("/journal add ''")

    def test_unclosed_quote(self):
        with pytest.raises(InstructionError, match="Could not tokenise"):
            parse_instruction("/buy AAPL 10 --thesis 'unclosed")
