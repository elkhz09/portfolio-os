"""Tests for /confirm refusing an order it cannot price.

Drives the real bot dispatcher (``_handle``) rather than a stand-in, because
the defect lived in the dispatcher: a market order on a never-held ticker
filled at a fabricated $1.00.
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.ledger import append_cash_entry, get_cash_balance
from app.db.models import (
    Base,
    CashEntryType,
    Holding,
    Order,
    OrderSide,
    OrderStatus,
    Trade,
)
from app.execution.paper_engine import PaperEngine
from app.interface.bot import _handle
from app.parser.command_parser import CommandName
from app.portfolio.state import PortfolioState
from app.reports.generator import ReportGenerator
from app.risk.checks import RiskChecker

USER = 4242


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def confirm(db, order_id: int) -> str:
    """Run the real /confirm handler against *db* and return the bot's reply."""
    state = PortfolioState(db)
    return asyncio.run(
        _handle(
            CommandName.CONFIRM,
            {"order_id": order_id},
            db,
            ReportGenerator(db),
            PaperEngine(db, state),
            RiskChecker(db),
            USER,
        )
    )


def queue(db, ticker: str, shares: float, limit_price: float | None = None) -> Order:
    order = Order(
        ticker=ticker,
        side=OrderSide.BUY,
        shares=shares,
        limit_price=limit_price,
        status=OrderStatus.PENDING,
        paper=True,
        telegram_user_id=USER,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


class TestConfirmRefusesUnpriceableOrders:
    def test_reply_is_a_refusal(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        order = queue(db, "NVDA", 50.0)
        reply = confirm(db, order.id)
        assert "🚫" in reply
        assert "✅" not in reply
        assert "Paper trade executed" not in reply

    def test_does_not_fill_at_one_dollar(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        order = queue(db, "NVDA", 50.0)
        reply = confirm(db, order.id)
        assert "$1.00" not in reply

    def test_no_trade_is_written(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        order = queue(db, "NVDA", 50.0)
        confirm(db, order.id)
        assert db.query(Trade).count() == 0

    def test_no_holding_is_created(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        order = queue(db, "NVDA", 50.0)
        confirm(db, order.id)
        assert db.query(Holding).filter_by(ticker="NVDA").first() is None

    def test_cash_is_untouched(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        db.commit()
        order = queue(db, "NVDA", 50.0)
        confirm(db, order.id)
        assert get_cash_balance(db) == 100_000.0

    def test_order_stays_pending_so_it_can_be_priced_and_retried(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        order = queue(db, "NVDA", 50.0)
        confirm(db, order.id)
        db.refresh(order)
        assert order.status == OrderStatus.PENDING

    def test_refusal_names_the_remedy(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        order = queue(db, "NVDA", 50.0)
        reply = confirm(db, order.id)
        assert "/price" in reply


class TestConfirmStillExecutesPriceableOrders:
    def test_limit_price_order_fills_at_the_limit(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        db.commit()
        order = queue(db, "NVDA", 10.0, limit_price=180.0)
        reply = confirm(db, order.id)
        db.refresh(order)
        assert order.status == OrderStatus.EXECUTED
        assert "$180.00" in reply
        assert get_cash_balance(db) == 100_000.0 - 1_800.0

    def test_market_order_fills_at_the_marked_price(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        db.add(Holding(ticker="NVDA", shares=1.0, avg_cost=100.0, last_price=200.0))
        db.commit()
        order = queue(db, "NVDA", 10.0)
        reply = confirm(db, order.id)
        db.refresh(order)
        assert order.status == OrderStatus.EXECUTED
        assert "$200.00" in reply

    def test_market_order_falls_back_to_avg_cost(self, db):
        append_cash_entry(db, CashEntryType.DEPOSIT, 100_000.0)
        db.add(Holding(ticker="NVDA", shares=1.0, avg_cost=150.0))
        db.commit()
        order = queue(db, "NVDA", 10.0)
        reply = confirm(db, order.id)
        db.refresh(order)
        assert order.status == OrderStatus.EXECUTED
        assert "$150.00" in reply

    def test_missing_order_still_reports_not_found(self, db):
        with pytest.raises(Exception, match="not found"):
            confirm(db, 999)
