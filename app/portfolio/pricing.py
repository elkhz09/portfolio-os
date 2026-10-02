"""Price resolution — the one place that answers what an order fills at.

There is no market data feed in this system, so a price can only come from
two places: a limit price the user typed on the order, or a price already
recorded against the holding. The policy is **fetch, or use what is known,
or refuse — never invent**:

1. an explicit limit price on the order,
2. the last marked price for the ticker (``/price TICKER VALUE``),
3. the holding's average cost, which is a price that was actually paid,
4. otherwise refuse, and say so.

A feed, if one is ever added, belongs at step 1 and nowhere else.

Both the risk layer and the Telegram interface call this. They used to answer
the question separately, which is how they came to disagree: the risk checks
skipped the cash test on a market order, and the bot filled a never-held
ticker at a placeholder $1.00.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Holding


@dataclass(frozen=True)
class PriceResolution:
    """A usable price, or a refusal explaining why there isn't one.

    Attributes:
        price: The resolved price, or None if the order cannot be priced.
        source: Where the price came from — ``limit``, ``last_price`` or
            ``avg_cost``. None on a refusal.
        reason: Human-readable refusal text. Set if and only if price is None.
    """

    price: float | None = None
    source: str | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        """True when a price was resolved."""
        return self.price is not None


def _usable(value: float | None) -> bool:
    return value is not None and value > 0


def resolve_price(
    db: Session,
    ticker: str,
    limit_price: float | None = None,
) -> PriceResolution:
    """Resolve the price to check and fill *ticker* at.

    Args:
        db: Active database session (read-only).
        ticker: Instrument symbol, case-insensitive.
        limit_price: Limit price supplied on the order, if any.

    Returns:
        A PriceResolution carrying either a price and its source, or a
        refusal reason. Never returns a fabricated price.
    """
    ticker = ticker.upper()

    if _usable(limit_price):
        return PriceResolution(price=float(limit_price), source="limit")

    holding: Holding | None = db.query(Holding).filter_by(ticker=ticker).first()
    if holding is not None:
        if _usable(holding.last_price):
            return PriceResolution(price=float(holding.last_price), source="last_price")
        if _usable(holding.avg_cost):
            return PriceResolution(price=float(holding.avg_cost), source="avg_cost")

    return PriceResolution(
        reason=(
            f"No price available for {ticker}. There is no market data feed, so "
            f"set a price with /price {ticker} VALUE, or put a limit price on the "
            f"order. Nothing is filled at a guessed price."
        )
    )
