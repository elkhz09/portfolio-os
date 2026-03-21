"""Portfolio analytics and P&L metrics."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.analytics.fifo import compute_realised_pnl
from app.db.ledger import get_cash_balance
from app.db.models import Holding


@dataclass
class PnLSummary:
    realised_pnl: float
    unrealised_pnl: float
    total_pnl: float
    total_cost_basis: float
    total_market_value: float
    cash_balance: float


class PortfolioMetrics:
    """Calculate performance metrics from trades and holdings.

    Args:
        session: Database session.
    """

    def __init__(self, session: Session) -> None:
        self._db = session

    def pnl_summary(self) -> PnLSummary:
        """Return aggregate P&L across all holdings and historical trades."""
        realised = self._realised_pnl()
        holdings = self._db.query(Holding).filter(Holding.shares > 0).all()

        unrealised = sum(
            (h.last_price - h.avg_cost) * h.shares
            for h in holdings
            if h.last_price is not None
        )
        cost_basis = sum(h.avg_cost * h.shares for h in holdings)
        market_value = sum(
            (h.last_price or h.avg_cost) * h.shares for h in holdings
        )

        return PnLSummary(
            realised_pnl=realised,
            unrealised_pnl=unrealised,
            total_pnl=realised + unrealised,
            total_cost_basis=cost_basis,
            total_market_value=market_value,
            cash_balance=get_cash_balance(self._db),
        )

    def ticker_pnl(self, ticker: str) -> dict:
        """Return P&L breakdown for a single ticker."""
        holding = self._db.query(Holding).filter_by(ticker=ticker.upper()).first()
        trades = (
            self._db.query(Trade)
            .filter_by(ticker=ticker.upper())
            .order_by(Trade.traded_at)
            .all()
        )

        realised = self._realised_pnl(ticker=ticker)
        unrealised = 0.0
        if holding and holding.last_price:
            unrealised = (holding.last_price - holding.avg_cost) * holding.shares

        return {
            "ticker": ticker,
            "current_shares": holding.shares if holding else 0.0,
            "avg_cost": holding.avg_cost if holding else 0.0,
            "last_price": holding.last_price if holding else None,
            "realised_pnl": realised,
            "unrealised_pnl": unrealised,
            "total_pnl": realised + unrealised,
            "trade_count": len(trades),
        }

    # ------------------------------------------------------------------

    def _realised_pnl(self, ticker: str | None = None) -> float:
        """Realised P&L computed via FIFO lot matching."""
        return compute_realised_pnl(self._db, ticker=ticker)
