"""Rebalance trade generation.

Computes the set of BUY/SELL orders required to bring current holdings
into alignment with stored TargetAllocation rows.

This module is pure computation — it does NOT create orders or touch
the database beyond reading. Order creation is the caller's responsibility.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.ledger import get_cash_balance
from app.db.models import Holding, OrderSide, TargetAllocation


@dataclass
class RebalanceTrade:
    """A single proposed trade to close allocation drift."""

    ticker: str
    side: OrderSide
    shares: float
    estimated_price: float
    estimated_value: float  # notional USD value of the trade


def compute_rebalance_trades(
    db: Session,
    min_trade_value: float = 100.0,
) -> list[RebalanceTrade]:
    """Compute trades needed to align holdings with target allocations.

    Uses last_price where available, falls back to avg_cost.
    Tickers with no price data are silently skipped (cannot size the trade).

    Sells are returned before buys so the caller can free up cash first.

    Args:
        db: Active database session (read-only).
        min_trade_value: Trades smaller than this USD notional are ignored
            to avoid churning tiny rounding differences. Default $100.

    Returns:
        Ordered list of RebalanceTrade — sells first, then buys.
    """
    holdings: dict[str, Holding] = {
        h.ticker: h
        for h in db.query(Holding).all()
    }
    targets: list[TargetAllocation] = db.query(TargetAllocation).all()

    if not targets:
        return []

    cash = get_cash_balance(db)
    equity = sum(
        (h.last_price or h.avg_cost) * h.shares
        for h in holdings.values()
        if h.shares > 0
    )
    total_aum = equity + cash

    if total_aum == 0:
        return []

    sells: list[RebalanceTrade] = []
    buys: list[RebalanceTrade] = []

    for target in targets:
        ticker = target.ticker
        holding = holdings.get(ticker)

        # Price estimate: last_price preferred, then avg_cost, then skip
        price: float | None = None
        if holding is not None:
            price = holding.last_price or (holding.avg_cost if holding.avg_cost > 0 else None)
        if price is None or price == 0:
            continue

        current_shares = holding.shares if holding else 0.0
        current_value = current_shares * price
        target_value = target.target_weight * total_aum
        delta_value = target_value - current_value

        if abs(delta_value) < min_trade_value:
            continue

        shares = abs(delta_value) / price

        if delta_value < 0:
            # Overweight — sell down to target
            shares = min(shares, current_shares)  # can't sell more than held
            if shares <= 0:
                continue
            sells.append(
                RebalanceTrade(
                    ticker=ticker,
                    side=OrderSide.SELL,
                    shares=round(shares, 6),
                    estimated_price=price,
                    estimated_value=abs(delta_value),
                )
            )
        else:
            # Underweight — buy up to target
            buys.append(
                RebalanceTrade(
                    ticker=ticker,
                    side=OrderSide.BUY,
                    shares=round(shares, 6),
                    estimated_price=price,
                    estimated_value=delta_value,
                )
            )

    # Sells first: frees cash so subsequent buys have room
    return sells + buys
