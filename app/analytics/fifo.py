"""FIFO lot tracker for realised P&L calculation.

Processes trades in chronological order. BUY trades open lots; SELL trades
consume lots from the front of the queue (first-in, first-out).

Note: this is an approximation for paper-mode tracking. For tax-accurate
calculations a full lot ledger with cost-basis elections would be required.
"""

from collections import deque

from sqlalchemy.orm import Session

from app.db.models import OrderSide, Trade


def compute_realised_pnl(db: Session, ticker: str | None = None) -> float:
    """Compute realised P&L across all (or one) ticker using FIFO lot matching.

    Args:
        db: Database session.
        ticker: If provided, restrict calculation to this ticker.

    Returns:
        Total realised P&L in dollars (positive = profit, negative = loss).
    """
    query = db.query(Trade).order_by(Trade.traded_at, Trade.id)
    if ticker:
        query = query.filter_by(ticker=ticker.upper())
    trades = query.all()

    if not trades:
        return 0.0

    # Group by ticker, process each independently
    by_ticker: dict[str, list[Trade]] = {}
    for t in trades:
        by_ticker.setdefault(t.ticker, []).append(t)

    return sum(_fifo_pnl(ticker_trades) for ticker_trades in by_ticker.values())


def _fifo_pnl(trades: list[Trade]) -> float:
    """FIFO P&L for a single ticker's chronological trade list.

    Args:
        trades: All trades for one ticker, sorted oldest-first.

    Returns:
        Realised P&L for this ticker.
    """
    # Each lot is (cost_per_share, shares_remaining)
    lots: deque[tuple[float, float]] = deque()
    realised = 0.0

    for trade in trades:
        if trade.side == OrderSide.BUY:
            lots.append((trade.price, trade.shares))
        else:  # SELL
            shares_to_sell = trade.shares
            sell_price = trade.price

            while shares_to_sell > 1e-9 and lots:
                lot_cost, lot_shares = lots[0]

                if lot_shares <= shares_to_sell:
                    # Consume entire lot
                    realised += (sell_price - lot_cost) * lot_shares
                    shares_to_sell -= lot_shares
                    lots.popleft()
                else:
                    # Partial lot consumed
                    realised += (sell_price - lot_cost) * shares_to_sell
                    lots[0] = (lot_cost, lot_shares - shares_to_sell)
                    shares_to_sell = 0.0

    return realised
