"""Tests for the paper execution engine."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.ledger import get_cash_balance
from app.db.models import Base, Order, OrderSide, OrderStatus
from app.db.seed import seed_empty_portfolio
from app.execution.paper_engine import ExecutionError, PaperEngine
from app.portfolio.state import PortfolioState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def seeded_db(db):
    """Database with $100,000 starting cash."""
    seed_empty_portfolio(db, starting_cash=100_000.0)
    db.commit()
    return db


def _engine(db: Session) -> PaperEngine:
    return PaperEngine(db, PortfolioState(db))


def _pending(db: Session, ticker="AAPL", side=OrderSide.BUY, shares=10.0, limit_price=None) -> Order:
    o = Order(ticker=ticker, side=side, shares=shares, limit_price=limit_price,
              status=OrderStatus.PENDING)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


# ---------------------------------------------------------------------------
# confirm_order
# ---------------------------------------------------------------------------

class TestConfirmOrder:
    def test_pending_to_confirmed(self, db):
        order = _pending(db)
        result = _engine(db).confirm_order(order.id)
        assert result.status == OrderStatus.CONFIRMED
        assert result.confirmed_at is not None

    def test_confirmed_order_raises(self, db):
        order = _pending(db)
        eng = _engine(db)
        eng.confirm_order(order.id)
        with pytest.raises(ExecutionError, match="CONFIRMED"):
            eng.confirm_order(order.id)

    def test_missing_order_raises(self, db):
        with pytest.raises(ExecutionError, match="not found"):
            _engine(db).confirm_order(9999)

    def test_audit_log_written(self, db):
        from app.db.models import AuditLog
        order = _pending(db)
        _engine(db).confirm_order(order.id, user_id=42)
        entry = db.query(AuditLog).filter_by(event="ORDER_CONFIRMED").first()
        assert entry is not None
        assert entry.telegram_user_id == 42


# ---------------------------------------------------------------------------
# execute_order
# ---------------------------------------------------------------------------

class TestExecuteOrder:
    def test_buy_creates_holding(self, seeded_db):
        order = _pending(seeded_db, ticker="AAPL", shares=10.0, limit_price=150.0)
        eng = _engine(seeded_db)
        eng.confirm_order(order.id)
        eng.execute_order(order.id, market_price=150.0)

        holding = PortfolioState(seeded_db).get_holding("AAPL")
        assert holding is not None
        assert holding.shares == pytest.approx(10.0)
        assert holding.avg_cost == pytest.approx(150.0)

    def test_buy_decrements_cash(self, seeded_db):
        order = _pending(seeded_db, ticker="AAPL", shares=10.0, limit_price=150.0)
        eng = _engine(seeded_db)
        eng.confirm_order(order.id)
        eng.execute_order(order.id, market_price=150.0)
        assert get_cash_balance(seeded_db) == pytest.approx(100_000.0 - 1_500.0)

    def test_sell_increments_cash(self, seeded_db):
        eng = _engine(seeded_db)
        buy = _pending(seeded_db, ticker="AAPL", shares=10.0, limit_price=150.0)
        eng.confirm_order(buy.id)
        eng.execute_order(buy.id, market_price=150.0)

        sell = _pending(seeded_db, ticker="AAPL", side=OrderSide.SELL, shares=5.0, limit_price=160.0)
        eng.confirm_order(sell.id)
        eng.execute_order(sell.id, market_price=160.0)

        expected = 100_000.0 - 1_500.0 + 800.0
        assert get_cash_balance(seeded_db) == pytest.approx(expected)

    def test_limit_price_takes_priority_over_market(self, seeded_db):
        order = _pending(seeded_db, ticker="AAPL", shares=5.0, limit_price=140.0)
        eng = _engine(seeded_db)
        eng.confirm_order(order.id)
        trade = eng.execute_order(order.id, market_price=155.0)
        assert trade.price == pytest.approx(140.0)

    def test_market_price_used_when_no_limit(self, seeded_db):
        order = _pending(seeded_db, ticker="AAPL", shares=5.0)
        eng = _engine(seeded_db)
        eng.confirm_order(order.id)
        trade = eng.execute_order(order.id, market_price=155.0)
        assert trade.price == pytest.approx(155.0)

    def test_execute_unconfirmed_raises(self, seeded_db):
        order = _pending(seeded_db, limit_price=100.0)
        with pytest.raises(ExecutionError, match="CONFIRMED"):
            _engine(seeded_db).execute_order(order.id, market_price=100.0)

    def test_order_marked_executed(self, seeded_db):
        order = _pending(seeded_db, limit_price=100.0)
        eng = _engine(seeded_db)
        eng.confirm_order(order.id)
        eng.execute_order(order.id, market_price=100.0)
        db_order = seeded_db.get(Order, order.id)
        assert db_order.status == OrderStatus.EXECUTED
        assert db_order.executed_price == pytest.approx(100.0)
        assert db_order.executed_at is not None

    def test_avg_cost_weighted_across_multiple_buys(self, seeded_db):
        eng = _engine(seeded_db)
        o1 = _pending(seeded_db, ticker="SPY", shares=10.0, limit_price=400.0)
        eng.confirm_order(o1.id)
        eng.execute_order(o1.id, market_price=400.0)

        o2 = _pending(seeded_db, ticker="SPY", shares=10.0, limit_price=420.0)
        eng.confirm_order(o2.id)
        eng.execute_order(o2.id, market_price=420.0)

        holding = PortfolioState(seeded_db).get_holding("SPY")
        assert holding.shares == pytest.approx(20.0)
        assert holding.avg_cost == pytest.approx(410.0)  # (400*10 + 420*10) / 20

    def test_sell_reduces_shares(self, seeded_db):
        eng = _engine(seeded_db)
        buy = _pending(seeded_db, ticker="GLD", shares=20.0, limit_price=180.0)
        eng.confirm_order(buy.id)
        eng.execute_order(buy.id, market_price=180.0)

        sell = _pending(seeded_db, ticker="GLD", side=OrderSide.SELL, shares=8.0, limit_price=190.0)
        eng.confirm_order(sell.id)
        eng.execute_order(sell.id, market_price=190.0)

        holding = PortfolioState(seeded_db).get_holding("GLD")
        assert holding.shares == pytest.approx(12.0)

    def test_gross_value_stored_on_trade(self, seeded_db):
        order = _pending(seeded_db, shares=5.0, limit_price=200.0)
        eng = _engine(seeded_db)
        eng.confirm_order(order.id)
        trade = eng.execute_order(order.id, market_price=200.0)
        assert trade.gross_value == pytest.approx(1_000.0)


# ---------------------------------------------------------------------------
# cancel_order
# ---------------------------------------------------------------------------

class TestCancelOrder:
    def test_cancel_pending(self, db):
        order = _pending(db)
        result = _engine(db).cancel_order(order.id)
        assert result.status == OrderStatus.CANCELLED

    def test_cancel_confirmed(self, db):
        order = _pending(db)
        eng = _engine(db)
        eng.confirm_order(order.id)
        result = eng.cancel_order(order.id)
        assert result.status == OrderStatus.CANCELLED

    def test_cancel_executed_raises(self, seeded_db):
        order = _pending(seeded_db, limit_price=100.0)
        eng = _engine(seeded_db)
        eng.confirm_order(order.id)
        eng.execute_order(order.id, market_price=100.0)
        with pytest.raises(ExecutionError, match="cannot be cancelled"):
            eng.cancel_order(order.id)

    def test_cancel_missing_order_raises(self, db):
        with pytest.raises(ExecutionError, match="not found"):
            _engine(db).cancel_order(9999)
