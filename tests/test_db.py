"""Tests for database initialisation, models, and seed script."""

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db.ledger import append_cash_entry, get_cash_balance
from app.db.models import (
    AuditLog,
    Base,
    CashEntryType,
    CashLedger,
    Holding,
    Order,
    OrderSide,
    OrderStatus,
    TargetAllocation,
    ThesisEntry,
    Trade,
    TradeStatus,
)
from app.db.seed import seed_empty_portfolio


# ---------------------------------------------------------------------------
# Fixture: in-memory SQLite session
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """Fresh in-memory database for each test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_all_tables_created(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        expected = {
            "holdings",
            "target_allocations",
            "orders",
            "trades",
            "thesis_entries",
            "cash_ledger",
            "audit_log",
        }
        assert expected.issubset(table_names), (
            f"Missing tables: {expected - table_names}"
        )

    def test_tables_created_twice_is_safe(self):
        """create_all is idempotent."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Base.metadata.create_all(engine)  # should not raise


# ---------------------------------------------------------------------------
# Holding
# ---------------------------------------------------------------------------

class TestHolding:
    def test_create_holding(self, db):
        h = Holding(ticker="AAPL", shares=10.0, avg_cost=150.0)
        db.add(h)
        db.commit()
        db.refresh(h)
        assert h.id is not None
        assert h.ticker == "AAPL"
        assert h.shares == 10.0
        assert h.avg_cost == 150.0
        assert h.created_at is not None
        assert h.updated_at is not None

    def test_default_shares_and_avg_cost(self, db):
        h = Holding(ticker="GLD")
        db.add(h)
        db.commit()
        db.refresh(h)
        assert h.shares == 0.0
        assert h.avg_cost == 0.0

    def test_ticker_is_unique(self, db):
        db.add(Holding(ticker="SPY", shares=5.0, avg_cost=400.0))
        db.commit()
        db.add(Holding(ticker="SPY", shares=1.0, avg_cost=410.0))
        with pytest.raises(Exception):
            db.commit()

    def test_last_price_nullable(self, db):
        h = Holding(ticker="TLT", shares=20.0, avg_cost=90.0)
        db.add(h)
        db.commit()
        assert h.last_price is None


# ---------------------------------------------------------------------------
# TargetAllocation
# ---------------------------------------------------------------------------

class TestTargetAllocation:
    def test_create(self, db):
        ta = TargetAllocation(ticker="AAPL", target_weight=0.25)
        db.add(ta)
        db.commit()
        db.refresh(ta)
        assert ta.id is not None
        assert ta.ticker == "AAPL"
        assert ta.target_weight == pytest.approx(0.25)
        assert ta.set_at is not None

    def test_with_note_and_user(self, db):
        ta = TargetAllocation(
            ticker="GLD",
            target_weight=0.10,
            note="inflation hedge",
            set_by_user_id=42,
        )
        db.add(ta)
        db.commit()
        db.refresh(ta)
        assert ta.note == "inflation hedge"
        assert ta.set_by_user_id == 42

    def test_ticker_unique(self, db):
        db.add(TargetAllocation(ticker="SPY", target_weight=0.30))
        db.commit()
        db.add(TargetAllocation(ticker="SPY", target_weight=0.40))
        with pytest.raises(Exception):
            db.commit()


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------

class TestOrder:
    def test_create_pending_order(self, db):
        o = Order(ticker="MSFT", side=OrderSide.BUY, shares=5.0)
        db.add(o)
        db.commit()
        db.refresh(o)
        assert o.id is not None
        assert o.status == OrderStatus.PENDING
        assert o.paper is True
        assert o.created_at is not None
        assert o.confirmed_at is None
        assert o.executed_at is None

    def test_order_status_transitions(self, db):
        o = Order(ticker="AAPL", side=OrderSide.SELL, shares=2.0)
        db.add(o)
        db.commit()
        assert o.status == OrderStatus.PENDING

        o.status = OrderStatus.CONFIRMED
        db.commit()
        assert o.status == OrderStatus.CONFIRMED

        o.status = OrderStatus.EXECUTED
        db.commit()
        assert o.status == OrderStatus.EXECUTED

    def test_all_status_values_valid(self):
        assert set(OrderStatus) == {
            OrderStatus.PENDING,
            OrderStatus.CONFIRMED,
            OrderStatus.EXECUTED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        }

    def test_both_sides_valid(self):
        assert set(OrderSide) == {OrderSide.BUY, OrderSide.SELL}


# ---------------------------------------------------------------------------
# Trade
# ---------------------------------------------------------------------------

class TestTrade:
    def _make_order(self, db, ticker="AAPL", side=OrderSide.BUY, shares=10.0) -> Order:
        o = Order(ticker=ticker, side=side, shares=shares, status=OrderStatus.EXECUTED)
        db.add(o)
        db.flush()
        return o

    def test_create_trade(self, db):
        order = self._make_order(db)
        t = Trade(
            order_id=order.id,
            ticker="AAPL",
            side=OrderSide.BUY,
            shares=10.0,
            price=150.0,
            gross_value=1500.0,
        )
        db.add(t)
        db.commit()
        db.refresh(t)
        assert t.id is not None
        assert t.gross_value == pytest.approx(1500.0)
        assert t.status == TradeStatus.COMPLETE
        assert t.paper is True
        assert t.traded_at is not None

    def test_trade_order_relationship(self, db):
        order = self._make_order(db)
        t = Trade(
            order_id=order.id,
            ticker="AAPL",
            side=OrderSide.BUY,
            shares=10.0,
            price=150.0,
            gross_value=1500.0,
        )
        db.add(t)
        db.commit()
        db.refresh(order)
        assert order.trade is not None
        assert order.trade.id == t.id

    def test_trade_status_values(self):
        assert set(TradeStatus) == {TradeStatus.COMPLETE, TradeStatus.PARTIAL}


# ---------------------------------------------------------------------------
# ThesisEntry
# ---------------------------------------------------------------------------

class TestThesisEntry:
    def test_create_with_ticker(self, db):
        e = ThesisEntry(ticker="GLD", body="Gold as macro hedge against tail risks.")
        db.add(e)
        db.commit()
        db.refresh(e)
        assert e.id is not None
        assert e.ticker == "GLD"
        assert e.created_at is not None
        assert e.updated_at is not None

    def test_create_without_ticker(self, db):
        e = ThesisEntry(body="General macro view — risk-off.")
        db.add(e)
        db.commit()
        assert e.ticker is None
        assert e.order_id is None

    def test_linked_to_order(self, db):
        o = Order(ticker="TLT", side=OrderSide.BUY, shares=50.0)
        db.add(o)
        db.flush()
        e = ThesisEntry(ticker="TLT", order_id=o.id, body="Duration play.")
        db.add(e)
        db.commit()
        db.refresh(e)
        assert e.order_id == o.id


# ---------------------------------------------------------------------------
# CashLedger
# ---------------------------------------------------------------------------

class TestCashLedger:
    def test_initial_balance_is_zero(self, db):
        assert get_cash_balance(db) == 0.0

    def test_deposit_increases_balance(self, db):
        entry = append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0, note="seed")
        db.commit()
        assert entry.balance_after == pytest.approx(100_000.0)
        assert get_cash_balance(db) == pytest.approx(100_000.0)

    def test_buy_settlement_decreases_balance(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        db.commit()
        append_cash_entry(db, CashEntryType.BUY_SETTLEMENT, -5_000.0, note="BUY 10 AAPL")
        db.commit()
        assert get_cash_balance(db) == pytest.approx(95_000.0)

    def test_sell_settlement_increases_balance(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 50_000.0)
        db.commit()
        append_cash_entry(db, CashEntryType.SELL_SETTLEMENT, 3_000.0, note="SELL 10 AAPL")
        db.commit()
        assert get_cash_balance(db) == pytest.approx(53_000.0)

    def test_multiple_entries_chain_correctly(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        append_cash_entry(db, CashEntryType.BUY_SETTLEMENT, -10_000.0)
        append_cash_entry(db, CashEntryType.SELL_SETTLEMENT, 2_000.0)
        append_cash_entry(db, CashEntryType.FEE, -50.0)
        db.commit()
        assert get_cash_balance(db) == pytest.approx(91_950.0)

    def test_all_entry_types_valid(self):
        assert set(CashEntryType) == {
            CashEntryType.DEPOSIT,
            CashEntryType.WITHDRAWAL,
            CashEntryType.BUY_SETTLEMENT,
            CashEntryType.SELL_SETTLEMENT,
            CashEntryType.DIVIDEND,
            CashEntryType.FEE,
            CashEntryType.ADJUSTMENT,
        }

    def test_entry_has_timestamps(self, db):
        e = append_cash_entry(db, CashEntryType.DEPOSIT, 1000.0)
        db.commit()
        db.refresh(e)
        assert e.occurred_at is not None
        assert e.created_at is not None


# ---------------------------------------------------------------------------
# Seed script
# ---------------------------------------------------------------------------

class TestSeedEmptyPortfolio:
    def test_seed_creates_deposit_entry(self, db):
        result = seed_empty_portfolio(db, starting_cash=100_000.0)
        db.commit()
        assert result is not None
        assert result.entry_type == CashEntryType.DEPOSIT
        assert result.amount == pytest.approx(100_000.0)
        assert result.balance_after == pytest.approx(100_000.0)

    def test_seed_cash_balance_matches(self, db):
        seed_empty_portfolio(db, starting_cash=250_000.0)
        db.commit()
        assert get_cash_balance(db) == pytest.approx(250_000.0)

    def test_seed_writes_audit_log(self, db):
        seed_empty_portfolio(db)
        db.commit()
        entry = db.query(AuditLog).filter_by(event="PORTFOLIO_SEEDED").first()
        assert entry is not None

    def test_seed_is_idempotent(self, db):
        seed_empty_portfolio(db, starting_cash=100_000.0)
        db.commit()
        result = seed_empty_portfolio(db, starting_cash=50_000.0)
        db.commit()
        # Second call returns None and does not change the balance
        assert result is None
        assert get_cash_balance(db) == pytest.approx(100_000.0)

    def test_seed_note_is_stored(self, db):
        seed_empty_portfolio(db, note="Q1 2026 fund launch")
        db.commit()
        entry = db.query(CashLedger).first()
        assert entry.note == "Q1 2026 fund launch"

    def test_seed_rejects_zero_cash(self, db):
        with pytest.raises(ValueError, match="must be positive"):
            seed_empty_portfolio(db, starting_cash=0.0)

    def test_seed_rejects_negative_cash(self, db):
        with pytest.raises(ValueError, match="must be positive"):
            seed_empty_portfolio(db, starting_cash=-1000.0)
