"""Pre-trade risk checks.

All checks run before an order is accepted into PENDING state.
A failed check blocks the order from being created.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db.ledger import get_cash_balance
from app.db.models import Holding, Order, OrderSide, OrderStatus


@dataclass
class RiskResult:
    """Outcome of a risk check pass."""

    passed: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        lines = []
        for w in self.warnings:
            lines.append(f"⚠️  {w}")
        for e in self.errors:
            lines.append(f"🚫  {e}")
        return "\n".join(lines) if lines else "✅ All risk checks passed."


class RiskChecker:
    """Evaluate pre-trade risk rules.

    Rules are intentionally conservative — add more as needed.

    Args:
        session: Database session for reading current state.
        max_position_shares: Maximum shares allowed in a single holding.
        max_open_orders: Maximum number of PENDING/CONFIRMED orders allowed.
        max_concentration: Max fraction of total portfolio value in one ticker (0–1).
        tradable_allowlist: Set of permitted tickers. Empty set = allow all.
    """

    def __init__(
        self,
        session: Session,
        max_position_shares: float = 100_000.0,
        max_open_orders: int = 20,
        max_concentration: float = 0.40,
        tradable_allowlist: set[str] | None = None,
    ) -> None:
        self._db = session
        self.max_position_shares = max_position_shares
        self.max_open_orders = max_open_orders
        self.max_concentration = max_concentration
        self.tradable_allowlist: set[str] = tradable_allowlist or set()

    def check_order(
        self,
        ticker: str,
        side: OrderSide,
        shares: float,
        limit_price: float | None = None,
    ) -> RiskResult:
        """Run all pre-trade checks for a proposed order.

        Args:
            ticker: Instrument symbol.
            side: BUY or SELL.
            shares: Proposed share count.
            limit_price: Optional limit price.

        Returns:
            RiskResult with passed=True if no errors (warnings may still be present).
        """
        ticker = ticker.upper()
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Tradable allowlist
        if self.tradable_allowlist and ticker not in self.tradable_allowlist:
            errors.append(
                f"{ticker} is not on the tradable allowlist. "
                f"Permitted: {', '.join(sorted(self.tradable_allowlist))}"
            )

        # 2. Positive shares
        if shares <= 0:
            errors.append(f"Share count must be positive, got {shares}")

        # 3. Duplicate open order for same ticker + side
        duplicate = (
            self._db.query(Order)
            .filter(
                Order.ticker == ticker,
                Order.side == side,
                Order.status.in_([OrderStatus.PENDING, OrderStatus.CONFIRMED]),
            )
            .first()
        )
        if duplicate is not None:
            errors.append(
                f"Duplicate open {side.value} order for {ticker} already exists "
                f"(order #{duplicate.id}, status={duplicate.status.value}). "
                "Cancel or confirm it first."
            )

        # 4. Open orders limit
        open_count = (
            self._db.query(Order)
            .filter(Order.status.in_([OrderStatus.PENDING, OrderStatus.CONFIRMED]))
            .count()
        )
        if open_count >= self.max_open_orders:
            errors.append(
                f"Too many open orders ({open_count}/{self.max_open_orders}). "
                "Cancel or confirm existing orders first."
            )

        # 5. Position shares limit (BUY only)
        holding: Holding | None = self._db.query(Holding).filter_by(ticker=ticker).first()
        current_shares = holding.shares if holding else 0.0

        if side == OrderSide.BUY:
            projected = current_shares + shares
            if projected > self.max_position_shares:
                errors.append(
                    f"Order would grow {ticker} position to {projected:,.0f} shares "
                    f"(limit {self.max_position_shares:,.0f})"
                )

        # 6. Sell more than held (no short selling)
        if side == OrderSide.SELL and shares > current_shares:
            errors.append(
                f"Cannot sell {shares} {ticker} — only {current_shares} held. "
                "Short selling is not supported."
            )

        # 7. Sufficient cash for buy (if limit price is known)
        if side == OrderSide.BUY and limit_price:
            order_cost = shares * limit_price
            cash = get_cash_balance(self._db)
            if order_cost > cash:
                errors.append(
                    f"Insufficient cash: order costs ${order_cost:,.2f} "
                    f"but cash balance is ${cash:,.2f}"
                )

        # 8. Concentration warning (informational only)
        if limit_price and side == OrderSide.BUY:
            order_value = shares * limit_price
            total_value = self._total_portfolio_value()
            if total_value > 0:
                projected_concentration = (
                    (current_shares * (holding.avg_cost if holding else 0) + order_value)
                    / (total_value + order_value)
                )
                if projected_concentration > self.max_concentration:
                    warnings.append(
                        f"This order would put {projected_concentration:.0%} of portfolio "
                        f"in {ticker} (limit {self.max_concentration:.0%})"
                    )

        return RiskResult(passed=len(errors) == 0, warnings=warnings, errors=errors)

    # ------------------------------------------------------------------

    def _total_portfolio_value(self) -> float:
        rows = self._db.query(Holding).all()
        return sum(
            (h.last_price or h.avg_cost) * h.shares for h in rows if h.shares > 0
        )
