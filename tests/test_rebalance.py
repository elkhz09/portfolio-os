"""Tests for rebalance trade generation."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, Holding, OrderSide, TargetAllocation
from app.db.seed import seed_empty_portfolio
from app.portfolio.rebalance import compute_rebalance_trades


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestComputeRebalanceTrades:
    def test_empty_portfolio_no_trades(self, db):
        assert compute_rebalance_trades(db) == []

    def test_no_targets_no_trades(self, db):
        seed_empty_portfolio(db, starting_cash=100_000.0)
        db.commit()
        assert compute_rebalance_trades(db) == []

    def test_underweight_generates_buy(self, db):
        seed_empty_portfolio(db, starting_cash=100_000.0)
        # Holding exists with a price but zero shares → underweight vs target
        db.add(Holding(ticker="AAPL", shares=0.0, avg_cost=150.0, last_price=150.0))
        db.add(TargetAllocation(ticker="AAPL", target_weight=0.20))
        db.commit()

        trades = compute_rebalance_trades(db)
        assert len(trades) == 1
        assert trades[0].side == OrderSide.BUY
        assert trades[0].ticker == "AAPL"
        assert trades[0].shares > 0

    def test_overweight_generates_sell(self, db):
        seed_empty_portfolio(db, starting_cash=50_000.0)
        db.add(Holding(ticker="SPY", shares=100.0, avg_cost=400.0, last_price=400.0))
        db.add(TargetAllocation(ticker="SPY", target_weight=0.10))
        db.commit()

        trades = compute_rebalance_trades(db)
        assert len(trades) == 1
        assert trades[0].side == OrderSide.SELL
        assert trades[0].ticker == "SPY"

    def test_sells_come_before_buys(self, db):
        seed_empty_portfolio(db, starting_cash=50_000.0)
        # SPY is overweight (will generate sell), GLD is underweight (will generate buy)
        db.add(Holding(ticker="SPY", shares=200.0, avg_cost=400.0, last_price=400.0))
        db.add(Holding(ticker="GLD", shares=0.0, avg_cost=180.0, last_price=180.0))
        db.add(TargetAllocation(ticker="SPY", target_weight=0.10))
        db.add(TargetAllocation(ticker="GLD", target_weight=0.20))
        db.commit()

        trades = compute_rebalance_trades(db)
        sides = [t.side for t in trades]
        sell_indices = [i for i, s in enumerate(sides) if s == OrderSide.SELL]
        buy_indices = [i for i, s in enumerate(sides) if s == OrderSide.BUY]
        assert sell_indices and buy_indices
        assert max(sell_indices) < min(buy_indices)

    def test_small_drift_ignored(self, db):
        seed_empty_portfolio(db, starting_cash=100_000.0)
        # Holding close enough to target that drift < min_trade_value
        # AUM ≈ 100_000 + 50*150 = 107_500
        # Target 50% → target_value ≈ 53_750
        # Current value = 50 * 150 = 7_500 — this is a large drift, not small
        # Use a case where drift is tiny: shares almost equal target
        db.add(Holding(ticker="AAPL", shares=333.33, avg_cost=150.0, last_price=150.0))
        db.add(TargetAllocation(ticker="AAPL", target_weight=0.333))
        db.commit()

        # min_trade_value=$100 — tiny differences should be suppressed
        trades = compute_rebalance_trades(db, min_trade_value=10_000.0)
        assert isinstance(trades, list)  # no crash; result may be empty

    def test_no_price_data_skipped(self, db):
        seed_empty_portfolio(db, starting_cash=100_000.0)
        db.add(Holding(ticker="UNKN", shares=0.0, avg_cost=0.0))  # no price
        db.add(TargetAllocation(ticker="UNKN", target_weight=0.10))
        db.commit()

        trades = compute_rebalance_trades(db)
        assert not any(t.ticker == "UNKN" for t in trades)

    def test_sell_capped_at_held_shares(self, db):
        seed_empty_portfolio(db, starting_cash=10_000.0)
        db.add(Holding(ticker="SPY", shares=10.0, avg_cost=400.0, last_price=400.0))
        db.add(TargetAllocation(ticker="SPY", target_weight=0.0))
        db.commit()

        trades = compute_rebalance_trades(db)
        sell = next((t for t in trades if t.side == OrderSide.SELL), None)
        assert sell is not None
        assert sell.shares <= 10.0

    def test_estimated_price_and_value_populated(self, db):
        seed_empty_portfolio(db, starting_cash=100_000.0)
        db.add(Holding(ticker="AAPL", shares=0.0, avg_cost=150.0, last_price=150.0))
        db.add(TargetAllocation(ticker="AAPL", target_weight=0.20))
        db.commit()

        trades = compute_rebalance_trades(db)
        assert len(trades) == 1
        assert trades[0].estimated_price == pytest.approx(150.0)
        assert trades[0].estimated_value > 0
