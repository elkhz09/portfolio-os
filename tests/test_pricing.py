"""Tests for the single price resolver.

The resolver is the one place that answers "what does this order fill at".
Its whole job is to return a known price or refuse — never to invent one.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, Holding
from app.portfolio.pricing import PriceResolution, resolve_price


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestExplicitLimitPrice:
    def test_limit_price_wins(self, db):
        db.add(Holding(ticker="NVDA", shares=1.0, avg_cost=400.0, last_price=500.0))
        db.commit()
        res = resolve_price(db, "NVDA", limit_price=123.0)
        assert res.ok
        assert res.price == 123.0
        assert res.source == "limit"

    def test_limit_price_works_with_no_holding(self, db):
        res = resolve_price(db, "NVDA", limit_price=180.0)
        assert res.ok
        assert res.price == 180.0


class TestKnownPrices:
    def test_last_price_preferred_over_avg_cost(self, db):
        db.add(Holding(ticker="NVDA", shares=1.0, avg_cost=400.0, last_price=500.0))
        db.commit()
        res = resolve_price(db, "NVDA")
        assert res.price == 500.0
        assert res.source == "last_price"

    def test_avg_cost_used_when_no_mark(self, db):
        db.add(Holding(ticker="NVDA", shares=1.0, avg_cost=400.0, last_price=None))
        db.commit()
        res = resolve_price(db, "NVDA")
        assert res.price == 400.0
        assert res.source == "avg_cost"

    def test_ticker_is_case_insensitive(self, db):
        db.add(Holding(ticker="NVDA", shares=1.0, avg_cost=400.0, last_price=500.0))
        db.commit()
        assert resolve_price(db, "nvda").price == 500.0


class TestRefusal:
    def test_never_held_ticker_is_refused(self, db):
        res = resolve_price(db, "NVDA")
        assert not res.ok
        assert res.price is None
        assert res.reason is not None

    def test_refusal_names_the_ticker_and_the_remedy(self, db):
        res = resolve_price(db, "NVDA")
        assert "NVDA" in res.reason
        assert "/price" in res.reason

    def test_does_not_invent_one_dollar(self, db):
        """The defect this module exists to close: a $1.00 placeholder fill."""
        res = resolve_price(db, "NVDA")
        assert res.price != 1.0

    def test_zero_prices_are_not_a_price(self, db):
        db.add(Holding(ticker="FLAT", shares=10.0, avg_cost=0.0, last_price=0.0))
        db.commit()
        res = resolve_price(db, "FLAT")
        assert not res.ok

    def test_negative_prices_are_not_a_price(self, db):
        db.add(Holding(ticker="BAD", shares=10.0, avg_cost=-5.0, last_price=-1.0))
        db.commit()
        res = resolve_price(db, "BAD")
        assert not res.ok

    def test_nonpositive_limit_price_falls_through_to_known(self, db):
        db.add(Holding(ticker="NVDA", shares=1.0, avg_cost=400.0))
        db.commit()
        assert resolve_price(db, "NVDA", limit_price=0.0).price == 400.0

    def test_held_position_with_no_price_at_all_is_refused(self, db):
        db.add(Holding(ticker="GHOST", shares=5.0, avg_cost=0.0, last_price=None))
        db.commit()
        assert not resolve_price(db, "GHOST").ok


class TestResolutionShape:
    def test_ok_is_false_exactly_when_price_is_none(self):
        assert PriceResolution(price=10.0, source="limit").ok
        assert not PriceResolution(reason="nope").ok

    def test_a_refusal_always_carries_a_reason(self, db):
        res = resolve_price(db, "UNKNOWN")
        assert not res.ok
        assert res.reason and res.reason.strip()
