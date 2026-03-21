"""SQLAlchemy ORM models.

Table layout
------------
holdings            Current equity/instrument positions
target_allocations  User-defined target portfolio weights
orders              User-initiated trade instructions (require confirmation)
trades              Immutable record of executed fills
thesis_entries      Free-text investment rationale notes
cash_ledger         Double-entry running cash balance
audit_log           Immutable event trail for all state changes
"""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class OrderSide(str, PyEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, PyEnum):
    PENDING = "PENDING"       # queued, awaiting user confirmation
    CONFIRMED = "CONFIRMED"   # user confirmed, awaiting execution
    EXECUTED = "EXECUTED"     # filled
    CANCELLED = "CANCELLED"   # user cancelled before execution
    REJECTED = "REJECTED"     # failed risk check or execution error


class TradeStatus(str, PyEnum):
    COMPLETE = "COMPLETE"  # fully filled
    PARTIAL = "PARTIAL"    # partially filled (future: broker partial fills)


class CashEntryType(str, PyEnum):
    DEPOSIT = "DEPOSIT"                 # cash added to the portfolio
    WITHDRAWAL = "WITHDRAWAL"           # cash removed from the portfolio
    BUY_SETTLEMENT = "BUY_SETTLEMENT"   # cash paid out on a buy trade
    SELL_SETTLEMENT = "SELL_SETTLEMENT" # cash received on a sell trade
    DIVIDEND = "DIVIDEND"               # dividend / coupon received
    FEE = "FEE"                         # commission or other fee
    ADJUSTMENT = "ADJUSTMENT"           # manual correction


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Holding(Base):
    """Current equity/instrument position for a single ticker.

    Updated in-place whenever a trade is executed.  Shares can be zero but
    the row is kept so that history is not lost.
    """

    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class TargetAllocation(Base):
    """User-defined target portfolio weight for a ticker.

    The system uses these weights to propose rebalance trades.  Setting a
    weight does not trigger any order — the user must request a rebalance
    explicitly.
    """

    __tablename__ = "target_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    target_weight: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    set_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    set_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Order(Base):
    """A trade order queued by the user.

    All orders start in PENDING status and must be explicitly confirmed
    before the execution engine will act on them.  This is the primary
    safeguard against unintended trades.
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide), nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False
    )
    paper: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    executed_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    telegram_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    trade: Mapped["Trade | None"] = relationship(
        "Trade", back_populates="order", uselist=False
    )
    thesis_entries: Mapped[list["ThesisEntry"]] = relationship(
        "ThesisEntry", back_populates="order"
    )


class Trade(Base):
    """Immutable record of an executed fill.

    Created by the execution engine when an Order is filled.  Never mutated
    after creation — the audit trail depends on this.
    """

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide), nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    gross_value: Mapped[float] = mapped_column(Float, nullable=False)  # price * shares
    status: Mapped[TradeStatus] = mapped_column(
        Enum(TradeStatus), default=TradeStatus.COMPLETE, nullable=False
    )
    paper: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    traded_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    order: Mapped["Order"] = relationship("Order", back_populates="trade")


class ThesisEntry(Base):
    """User-authored investment rationale note.

    Can be attached to a specific ticker, a specific order, or both.
    Free-text; the user is the sole author.
    """

    __tablename__ = "thesis_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    telegram_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    order: Mapped["Order | None"] = relationship("Order", back_populates="thesis_entries")


class CashLedger(Base):
    """Double-entry running cash balance.

    Every event that moves cash creates a new immutable row.
    ``balance_after`` is a snapshot of the total cash balance immediately
    after this entry, making it cheap to query the current balance.

    Positive ``amount``  = cash inflow  (deposit, sell proceeds, dividend).
    Negative ``amount``  = cash outflow (withdrawal, buy cost, fee).
    """

    __tablename__ = "cash_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_type: Mapped[CashEntryType] = mapped_column(
        Enum(CashEntryType), nullable=False
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    balance_after: Mapped[float] = mapped_column(Float, nullable=False)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True, index=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class AuditLog(Base):
    """Immutable audit trail for all state-changing events.

    Append-only.  Never update or delete rows from this table.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
