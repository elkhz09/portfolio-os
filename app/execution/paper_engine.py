"""Paper execution engine.

Simulates order fills without touching any live brokerage.
All orders must be in CONFIRMED status before execution.
"""

from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from app.db.ledger import append_cash_entry
from app.db.models import AuditLog, CashEntryType, Order, OrderSide, OrderStatus, Trade
from app.portfolio.state import PortfolioState


class ExecutionError(RuntimeError):
    """Raised when an order cannot be executed."""


class PaperEngine:
    """Execute confirmed orders in paper (simulated) mode.

    Args:
        session: Active database session.
        portfolio: PortfolioState instance to update after trades.
    """

    def __init__(self, session: Session, portfolio: PortfolioState) -> None:
        self._db = session
        self._portfolio = portfolio

    def confirm_order(self, order_id: int, user_id: int | None = None) -> Order:
        """Move an order from PENDING → CONFIRMED.

        Args:
            order_id: ID of the order to confirm.
            user_id: Telegram user ID for audit logging.

        Returns:
            The updated Order.

        Raises:
            ExecutionError: If the order is not in PENDING status.
        """
        order = self._get_order(order_id)
        if order.status != OrderStatus.PENDING:
            raise ExecutionError(
                f"Order {order_id} is {order.status.value}, expected PENDING"
            )
        order.status = OrderStatus.CONFIRMED
        order.confirmed_at = datetime.utcnow()
        self._audit("ORDER_CONFIRMED", f"order_id={order_id}", user_id)
        self._db.commit()
        logger.info("Order {} confirmed by user {}", order_id, user_id)
        return order

    def execute_order(self, order_id: int, market_price: float) -> Trade:
        """Execute a CONFIRMED order at *market_price* (paper fill).

        Args:
            order_id: ID of the confirmed order.
            market_price: Simulated fill price.

        Returns:
            The resulting Trade record.

        Raises:
            ExecutionError: If the order is not CONFIRMED.
        """
        order = self._get_order(order_id)
        if order.status != OrderStatus.CONFIRMED:
            raise ExecutionError(
                f"Order {order_id} must be CONFIRMED before execution, "
                f"got {order.status.value}"
            )

        fill_price = order.limit_price if order.limit_price else market_price
        gross_value = fill_price * order.shares

        trade = Trade(
            order_id=order.id,
            ticker=order.ticker,
            side=order.side,
            shares=order.shares,
            price=fill_price,
            gross_value=gross_value,
            paper=True,
            traded_at=datetime.utcnow(),
        )
        self._db.add(trade)

        order.status = OrderStatus.EXECUTED
        order.executed_price = fill_price
        order.executed_at = datetime.utcnow()

        self._db.flush()  # assign trade.id before portfolio/cash updates

        # Update holding and cash ledger
        self._portfolio.apply_trade(trade)

        if order.side == OrderSide.BUY:
            append_cash_entry(
                self._db,
                CashEntryType.BUY_SETTLEMENT,
                amount=-gross_value,
                order_id=order.id,
                note=f"BUY {order.shares} {order.ticker} @ {fill_price:.4f}",
            )
        else:
            append_cash_entry(
                self._db,
                CashEntryType.SELL_SETTLEMENT,
                amount=gross_value,
                order_id=order.id,
                note=f"SELL {order.shares} {order.ticker} @ {fill_price:.4f}",
            )

        self._audit(
            "ORDER_EXECUTED",
            f"order_id={order_id} ticker={order.ticker} "
            f"side={order.side.value} shares={order.shares} price={fill_price}",
        )
        self._db.commit()
        logger.info(
            "Paper trade: {} {} {} @ {}",
            order.side.value, order.shares, order.ticker, fill_price,
        )
        return trade

    def cancel_order(self, order_id: int, user_id: int | None = None) -> Order:
        """Cancel a PENDING or CONFIRMED order.

        Args:
            order_id: ID of the order to cancel.
            user_id: Telegram user ID for audit logging.

        Returns:
            The updated Order.

        Raises:
            ExecutionError: If the order cannot be cancelled.
        """
        order = self._get_order(order_id)
        if order.status not in (OrderStatus.PENDING, OrderStatus.CONFIRMED):
            raise ExecutionError(
                f"Order {order_id} cannot be cancelled (status={order.status.value})"
            )
        order.status = OrderStatus.CANCELLED
        self._audit("ORDER_CANCELLED", f"order_id={order_id}", user_id)
        self._db.commit()
        logger.info("Order {} cancelled by user {}", order_id, user_id)
        return order

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_order(self, order_id: int) -> Order:
        order = self._db.get(Order, order_id)
        if order is None:
            raise ExecutionError(f"Order {order_id} not found")
        return order

    def _audit(self, event: str, detail: str = "", user_id: int | None = None) -> None:
        entry = AuditLog(event=event, detail=detail, telegram_user_id=user_id)
        self._db.add(entry)
