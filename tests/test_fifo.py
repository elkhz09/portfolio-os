"""Tests for FIFO lot-based realised P&L calculation."""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, Order, OrderSide, OrderStatus, Trade
from app.analytics.fifo import compute_realised_pnl

_T0 = datetime(2026, 1, 1)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _order(db: Session, ticker: str, side: OrderSide, shares: float) -> Order:
    o = Order(ticker=ticker, side=side, shares=shares, status=OrderStatus.EXECUTED)
    db.add(o)
    db.flush()
    return o


def _trade(db: Session, order: Order, price: float, offset: int = 0) -> Trade:
    t = Trade(
        order_id=order.id,
        ticker=order.ticker,
        side=order.side,
        shares=order.shares,
        price=price,
        gross_value=price * order.shares,
        paper=True,
        traded_at=_T0 + timedelta(seconds=offset),
    )
    db.add(t)
    db.flush()
    return t


# ---------------------------------------------------------------------------

class TestFifo:
    def test_no_trades_zero_pnl(self, db):
        assert compute_realised_pnl(db) == 0.0

    def test_buy_only_zero_pnl(self, db):
        o = _order(db, "AAPL", OrderSide.BUY, 10.0)
        _trade(db, o, 150.0)
        db.commit()
        assert compute_realised_pnl(db) == 0.0

    def test_buy_then_full_sell_profit(self, db):
        o1 = _order(db, "AAPL", OrderSide.BUY, 10.0)
        _trade(db, o1, 100.0, offset=0)
        o2 = _order(db, "AAPL", OrderSide.SELL, 10.0)
        _trade(db, o2, 120.0, offset=1)
        db.commit()
        assert compute_realised_pnl(db) == pytest.approx(200.0)  # (120-100)*10

    def test_buy_then_full_sell_loss(self, db):
        o1 = _order(db, "AAPL", OrderSide.BUY, 10.0)
        _trade(db, o1, 100.0, offset=0)
        o2 = _order(db, "AAPL", OrderSide.SELL, 10.0)
        _trade(db, o2, 80.0, offset=1)
        db.commit()
        assert compute_realised_pnl(db) == pytest.approx(-200.0)  # (80-100)*10

    def test_partial_sell_fifo_ordering(self, db):
        # Buy 10 @ 100, buy 10 @ 110, sell 15 @ 130
        # FIFO: consume all 10 from lot1, then 5 from lot2
        # PnL = (130-100)*10 + (130-110)*5 = 300 + 100 = 400
        o1 = _order(db, "SPY", OrderSide.BUY, 10.0)
        _trade(db, o1, 100.0, offset=0)
        o2 = _order(db, "SPY", OrderSide.BUY, 10.0)
        _trade(db, o2, 110.0, offset=1)
        o3 = _order(db, "SPY", OrderSide.SELL, 15.0)
        _trade(db, o3, 130.0, offset=2)
        db.commit()
        assert compute_realised_pnl(db) == pytest.approx(400.0)

    def test_ticker_filter_isolates_result(self, db):
        # AAPL: +$200 PnL
        o1 = _order(db, "AAPL", OrderSide.BUY, 10.0)
        _trade(db, o1, 100.0, offset=0)
        o2 = _order(db, "AAPL", OrderSide.SELL, 10.0)
        _trade(db, o2, 120.0, offset=1)
        # SPY: buy only (no realised PnL)
        o3 = _order(db, "SPY", OrderSide.BUY, 5.0)
        _trade(db, o3, 400.0, offset=2)
        db.commit()

        assert compute_realised_pnl(db, ticker="AAPL") == pytest.approx(200.0)
        assert compute_realised_pnl(db, ticker="SPY") == pytest.approx(0.0)

    def test_multi_ticker_aggregate(self, db):
        # AAPL: +$200, SPY: +$50
        o1 = _order(db, "AAPL", OrderSide.BUY, 10.0)
        _trade(db, o1, 100.0, offset=0)
        o2 = _order(db, "AAPL", OrderSide.SELL, 10.0)
        _trade(db, o2, 120.0, offset=1)

        o3 = _order(db, "SPY", OrderSide.BUY, 5.0)
        _trade(db, o3, 390.0, offset=2)
        o4 = _order(db, "SPY", OrderSide.SELL, 5.0)
        _trade(db, o4, 400.0, offset=3)
        db.commit()

        assert compute_realised_pnl(db) == pytest.approx(250.0)

    def test_remaining_lots_not_counted(self, db):
        # Buy 20, sell 10 — only the sold lot generates realised PnL
        o1 = _order(db, "GLD", OrderSide.BUY, 20.0)
        _trade(db, o1, 150.0, offset=0)
        o2 = _order(db, "GLD", OrderSide.SELL, 10.0)
        _trade(db, o2, 160.0, offset=1)
        db.commit()
        # Only 10 shares sold: PnL = (160-150)*10 = 100
        assert compute_realised_pnl(db) == pytest.approx(100.0)

    def test_multiple_sell_legs(self, db):
        # Buy 10 @ 100, sell 5 @ 110, sell 5 @ 120
        # PnL = (110-100)*5 + (120-100)*5 = 50 + 100 = 150
        o1 = _order(db, "TLT", OrderSide.BUY, 10.0)
        _trade(db, o1, 100.0, offset=0)
        o2 = _order(db, "TLT", OrderSide.SELL, 5.0)
        _trade(db, o2, 110.0, offset=1)
        o3 = _order(db, "TLT", OrderSide.SELL, 5.0)
        _trade(db, o3, 120.0, offset=2)
        db.commit()
        assert compute_realised_pnl(db) == pytest.approx(150.0)
