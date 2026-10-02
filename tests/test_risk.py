"""Tests for pre-trade risk checks."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.ledger import append_cash_entry
from app.db.models import (
    Base,
    CashEntryType,
    Holding,
    Order,
    OrderSide,
    OrderStatus,
)
from app.risk.checks import RiskChecker


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestBasicChecks:
    def test_basic_buy_passes(self, db):
        # A price is required for the order to be checkable at all, so give one.
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        db.commit()
        checker = RiskChecker(db)
        result = checker.check_order("AAPL", OrderSide.BUY, 10.0, limit_price=150.0)
        assert result.passed
        assert not result.errors

    def test_zero_shares_fails(self, db):
        checker = RiskChecker(db)
        result = checker.check_order("AAPL", OrderSide.BUY, 0.0)
        assert not result.passed
        assert any("positive" in e for e in result.errors)

    def test_negative_shares_fails(self, db):
        checker = RiskChecker(db)
        result = checker.check_order("AAPL", OrderSide.BUY, -5.0)
        assert not result.passed

    def test_sell_more_than_held_fails(self, db):
        checker = RiskChecker(db)
        result = checker.check_order("TSLA", OrderSide.SELL, 5.0)
        assert not result.passed
        assert any("Short selling" in e for e in result.errors)

    def test_sell_within_position_passes(self, db):
        db.add(Holding(ticker="TSLA", shares=100.0, avg_cost=200.0))
        db.commit()
        checker = RiskChecker(db)
        result = checker.check_order("TSLA", OrderSide.SELL, 50.0)
        assert result.passed

    def test_position_shares_limit(self, db):
        checker = RiskChecker(db, max_position_shares=100.0)
        result = checker.check_order("SPY", OrderSide.BUY, 200.0)
        assert not result.passed
        assert any("limit" in e.lower() for e in result.errors)


class TestCashCheck:
    def test_insufficient_cash_for_buy_fails(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 1_000.0)
        db.commit()
        checker = RiskChecker(db)
        result = checker.check_order("AAPL", OrderSide.BUY, 10.0, limit_price=200.0)
        assert not result.passed
        assert any("cash" in e.lower() for e in result.errors)

    def test_sufficient_cash_passes(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        db.commit()
        checker = RiskChecker(db)
        result = checker.check_order("AAPL", OrderSide.BUY, 10.0, limit_price=150.0)
        assert result.passed


class TestConcentrationWarning:
    def test_concentration_warning_issued(self, db):
        # Seed enough cash so the cash check doesn't interfere
        append_cash_entry(db, CashEntryType.DEPOSIT, 500_000.0)
        db.add(Holding(ticker="GOOG", shares=10.0, avg_cost=100.0, last_price=100.0))
        db.commit()
        checker = RiskChecker(db, max_concentration=0.30)
        result = checker.check_order("AAPL", OrderSide.BUY, 100.0, limit_price=100.0)
        assert result.passed  # warnings only, not errors
        assert any("%" in w or "concentration" in w.lower() for w in result.warnings)

    def test_no_concentration_warning_when_small(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 500_000.0)
        db.add(Holding(ticker="GOOG", shares=100.0, avg_cost=100.0, last_price=100.0))
        db.commit()
        checker = RiskChecker(db, max_concentration=0.40)
        result = checker.check_order("AAPL", OrderSide.BUY, 1.0, limit_price=100.0)
        assert result.passed
        assert not result.warnings


class TestAllowlist:
    def test_ticker_not_in_allowlist_fails(self, db):
        checker = RiskChecker(db, tradable_allowlist={"AAPL", "SPY"})
        result = checker.check_order("TSLA", OrderSide.BUY, 5.0)
        assert not result.passed
        assert any("not on" in e.lower() or "allowlist" in e.lower() for e in result.errors)

    def test_ticker_in_allowlist_passes(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        db.commit()
        checker = RiskChecker(db, tradable_allowlist={"AAPL", "SPY"})
        result = checker.check_order("AAPL", OrderSide.BUY, 5.0, limit_price=150.0)
        assert result.passed

    def test_empty_allowlist_allows_all(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        db.commit()
        checker = RiskChecker(db, tradable_allowlist=set())
        result = checker.check_order("ANYTHING", OrderSide.BUY, 1.0, limit_price=10.0)
        assert result.passed


class TestDuplicateOrderCheck:
    def test_duplicate_open_order_fails(self, db):
        db.add(Order(ticker="AAPL", side=OrderSide.BUY, shares=5.0, status=OrderStatus.PENDING))
        db.commit()
        checker = RiskChecker(db)
        result = checker.check_order("AAPL", OrderSide.BUY, 10.0)
        assert not result.passed
        assert any("duplicate" in e.lower() or "open" in e.lower() for e in result.errors)

    def test_confirmed_order_also_blocks_duplicate(self, db):
        db.add(Order(ticker="SPY", side=OrderSide.BUY, shares=5.0, status=OrderStatus.CONFIRMED))
        db.commit()
        checker = RiskChecker(db)
        result = checker.check_order("SPY", OrderSide.BUY, 10.0)
        assert not result.passed

    def test_executed_order_does_not_block(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        db.add(Order(ticker="GLD", side=OrderSide.BUY, shares=5.0, status=OrderStatus.EXECUTED))
        db.commit()
        checker = RiskChecker(db)
        result = checker.check_order("GLD", OrderSide.BUY, 10.0, limit_price=200.0)
        assert result.passed

    def test_different_side_does_not_block(self, db):
        db.add(Holding(ticker="AAPL", shares=20.0, avg_cost=150.0))
        db.add(Order(ticker="AAPL", side=OrderSide.BUY, shares=5.0, status=OrderStatus.PENDING))
        db.commit()
        checker = RiskChecker(db)
        result = checker.check_order("AAPL", OrderSide.SELL, 5.0)
        assert result.passed


class TestMarketOrderPricing:
    """A market order (no limit price) must still be checked, or refused.

    Before this, every check that needed a price was gated on limit_price
    being truthy, so a market BUY skipped the cash and concentration checks
    entirely: 50,000 NVDA passed on a $99,990 account.
    """

    def test_market_buy_on_unpriced_ticker_is_refused(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 99_990.0)
        db.commit()
        checker = RiskChecker(db)
        result = checker.check_order("NVDA", OrderSide.BUY, 50_000)
        assert not result.passed
        assert any("price" in e.lower() for e in result.errors)

    def test_refusal_points_at_the_remedy(self, db):
        result = RiskChecker(db).check_order("NVDA", OrderSide.BUY, 10)
        assert not result.passed
        assert any("/price" in e for e in result.errors)

    def test_market_buy_is_cash_checked_against_last_price(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 1_000.0)
        db.add(Holding(ticker="NVDA", shares=1.0, avg_cost=400.0, last_price=500.0))
        db.commit()
        result = RiskChecker(db).check_order("NVDA", OrderSide.BUY, 50)
        assert not result.passed
        assert any("cash" in e.lower() for e in result.errors)

    def test_market_buy_is_cash_checked_against_avg_cost(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 1_000.0)
        db.add(Holding(ticker="NVDA", shares=1.0, avg_cost=400.0))
        db.commit()
        result = RiskChecker(db).check_order("NVDA", OrderSide.BUY, 50)
        assert not result.passed
        assert any("cash" in e.lower() for e in result.errors)

    def test_market_buy_within_cash_still_passes(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        db.add(Holding(ticker="NVDA", shares=1.0, avg_cost=100.0, last_price=100.0))
        db.commit()
        result = RiskChecker(db).check_order("NVDA", OrderSide.BUY, 10)
        assert result.passed

    def test_concentration_warning_fires_without_a_limit_price(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 500_000.0)
        db.add(Holding(ticker="GOOG", shares=10.0, avg_cost=100.0, last_price=100.0))
        db.add(Holding(ticker="AAPL", shares=1.0, avg_cost=100.0, last_price=100.0))
        db.commit()
        checker = RiskChecker(db, max_concentration=0.30)
        result = checker.check_order("AAPL", OrderSide.BUY, 100.0)
        assert result.passed
        assert result.warnings

    def test_unpriced_sell_is_refused_too(self, db):
        db.add(Holding(ticker="GHOST", shares=10.0, avg_cost=0.0, last_price=None))
        db.commit()
        result = RiskChecker(db).check_order("GHOST", OrderSide.SELL, 5.0)
        assert not result.passed
        assert any("price" in e.lower() for e in result.errors)

    def test_unpriceable_order_does_not_suppress_other_errors(self, db):
        """A missing price must not become the only thing reported."""
        checker = RiskChecker(db, max_position_shares=100.0)
        result = checker.check_order("SPY", OrderSide.BUY, 200.0)
        assert not result.passed
        assert any("price" in e.lower() for e in result.errors)
        assert any("limit" in e.lower() and "shares" in e.lower() for e in result.errors)
