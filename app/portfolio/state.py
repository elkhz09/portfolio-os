"""Portfolio state engine.

Reads and mutates holding records. Does not execute orders — that is the
responsibility of the execution engine.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.ledger import get_cash_balance
from app.db.models import Holding, OrderSide, TargetAllocation, Trade


@dataclass
class HoldingSnapshot:
    ticker: str
    shares: float
    avg_cost: float
    last_price: float | None
    unrealised_pnl: float | None

    @property
    def market_value(self) -> float | None:
        if self.last_price is None:
            return None
        return self.shares * self.last_price


class PortfolioState:
    """Read and update portfolio holdings from the database."""

    def __init__(self, session: Session) -> None:
        self._db = session

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_holding(self, ticker: str) -> Holding | None:
        """Return the Holding row for *ticker*, or None if not held."""
        return self._db.query(Holding).filter_by(ticker=ticker.upper()).first()

    def all_holdings(self) -> list[HoldingSnapshot]:
        """Return snapshots of all non-zero holdings."""
        rows = self._db.query(Holding).filter(Holding.shares != 0).all()
        return [self._to_snapshot(h) for h in rows]

    def snapshot(self) -> dict:
        """Return a dict summary suitable for display."""
        holdings = self.all_holdings()
        total_cost = sum(h.shares * h.avg_cost for h in holdings)
        total_market = sum(h.market_value or 0 for h in holdings)
        return {
            "positions": holdings,
            "total_cost_basis": total_cost,
            "total_market_value": total_market,
            "count": len(holdings),
        }

    def total_aum(self) -> float:
        """Return total assets under management: equity market value + cash."""
        holdings = self._db.query(Holding).filter(Holding.shares > 0).all()
        equity = sum((h.last_price or h.avg_cost) * h.shares for h in holdings)
        cash = get_cash_balance(self._db)
        return equity + cash

    def compute_weights(self) -> dict[str, float]:
        """Return current weight of each holding as a fraction of total AUM.

        Uses last_price when available, falls back to avg_cost.
        Returns an empty dict if AUM is zero.
        """
        aum = self.total_aum()
        if aum == 0:
            return {}
        holdings = self._db.query(Holding).filter(Holding.shares > 0).all()
        return {
            h.ticker: ((h.last_price or h.avg_cost) * h.shares) / aum
            for h in holdings
        }

    def compute_drift(self) -> dict[str, float]:
        """Return drift for each target allocation.

        Drift = target_weight - current_weight.
        Positive drift means underweight (need to buy).
        Negative drift means overweight (need to sell).
        """
        current = self.compute_weights()
        targets = self._db.query(TargetAllocation).all()
        return {
            t.ticker: t.target_weight - current.get(t.ticker, 0.0)
            for t in targets
        }

    # ------------------------------------------------------------------
    # Writes (called by the execution engine after a confirmed trade)
    # ------------------------------------------------------------------

    def apply_trade(self, trade: Trade) -> None:
        """Update (or create) a holding based on an executed trade.

        Args:
            trade: A Trade ORM object that has been flushed to the session.
        """
        holding = self.get_holding(trade.ticker)

        if holding is None:
            holding = Holding(ticker=trade.ticker, shares=0.0, avg_cost=0.0)
            self._db.add(holding)

        if trade.side == OrderSide.BUY:
            new_shares = holding.shares + trade.shares
            if new_shares == 0:
                holding.avg_cost = 0.0
            else:
                holding.avg_cost = (
                    holding.avg_cost * holding.shares + trade.price * trade.shares
                ) / new_shares
            holding.shares = new_shares
        else:  # SELL
            holding.shares -= trade.shares
            if holding.shares <= 0:
                holding.shares = 0.0
                holding.avg_cost = 0.0

        self._db.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_snapshot(h: Holding) -> HoldingSnapshot:
        unrealised = (
            (h.last_price - h.avg_cost) * h.shares if h.last_price is not None else None
        )
        return HoldingSnapshot(
            ticker=h.ticker,
            shares=h.shares,
            avg_cost=h.avg_cost,
            last_price=h.last_price,
            unrealised_pnl=unrealised,
        )
