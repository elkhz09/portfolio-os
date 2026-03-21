"""Report generators for portfolio summaries and audit trails."""

from sqlalchemy.orm import Session

from app.analytics.metrics import PortfolioMetrics
from app.db.ledger import get_cash_balance
from app.db.models import AuditLog, Order, OrderStatus, ThesisEntry, Trade
from app.portfolio.state import PortfolioState
from app.utils.time import fmt_sgt, now_sgt


class ReportGenerator:
    """Build text and structured reports from portfolio data.

    Args:
        session: Database session.
    """

    def __init__(self, session: Session) -> None:
        self._db = session
        self._state = PortfolioState(session)
        self._metrics = PortfolioMetrics(session)

    def portfolio_summary(self) -> str:
        """Return a human-readable portfolio snapshot string."""
        snap = self._state.snapshot()
        cash = get_cash_balance(self._db)
        lines = [
            f"Portfolio — {now_sgt().strftime('%Y-%m-%d %H:%M SGT')}",
            f"Holdings: {snap['count']}",
            f"Cost basis:   ${snap['total_cost_basis']:,.2f}",
            f"Market value: ${snap['total_market_value']:,.2f}",
            f"Cash balance: ${cash:,.2f}",
            "",
            "─" * 48,
        ]
        for h in snap["positions"]:
            mv = f"${h.market_value:,.2f}" if h.market_value is not None else "N/A"
            pnl = f"{h.unrealised_pnl:+,.2f}" if h.unrealised_pnl is not None else "N/A"
            lines.append(
                f"{h.ticker:<8} {h.shares:>12,.4f} sh  "
                f"avg ${h.avg_cost:,.2f}  mv {mv}  uPnL ${pnl}"
            )
        return "\n".join(lines)

    def pnl_report(self) -> str:
        """Return a P&L summary string."""
        s = self._metrics.pnl_summary()
        return (
            "P&L Summary\n"
            f"Realised:     ${s.realised_pnl:+,.2f}\n"
            f"Unrealised:   ${s.unrealised_pnl:+,.2f}\n"
            f"Total:        ${s.total_pnl:+,.2f}\n"
            f"Cost basis:   ${s.total_cost_basis:,.2f}\n"
            f"Market value: ${s.total_market_value:,.2f}\n"
            f"Cash:         ${s.cash_balance:,.2f}"
        )

    def journal_report(self, ticker: str | None = None, limit: int = 20) -> str:
        """Return recent thesis journal entries as a string."""
        query = self._db.query(ThesisEntry).order_by(ThesisEntry.created_at.desc())
        if ticker:
            query = query.filter_by(ticker=ticker.upper())
        entries = query.limit(limit).all()

        if not entries:
            return "No journal entries found."

        lines = [f"Thesis Journal{f' — {ticker}' if ticker else ''}", "─" * 40]
        for e in entries:
            stamp = fmt_sgt(e.created_at)
            tag = f"[{e.ticker}] " if e.ticker else ""
            lines.append(f"{stamp}  {tag}{e.body}")
        return "\n".join(lines)

    def audit_tail(self, limit: int = 50) -> str:
        """Return the most recent audit log entries as a string."""
        rows = (
            self._db.query(AuditLog)
            .order_by(AuditLog.occurred_at.desc())
            .limit(limit)
            .all()
        )
        if not rows:
            return "Audit log is empty."
        lines = ["Audit Log (most recent first)", "─" * 40]
        for r in rows:
            stamp = fmt_sgt(r.occurred_at, "%Y-%m-%d %H:%M:%S")
            lines.append(f"{stamp}  {r.event:<24} {r.detail or ''}")
        return "\n".join(lines)

    def trade_history_report(self, ticker: str | None = None, limit: int = 30) -> str:
        """Return recent executed trades as a string."""
        query = self._db.query(Trade).order_by(Trade.traded_at.desc())
        if ticker:
            query = query.filter_by(ticker=ticker.upper())
        trades = query.limit(limit).all()

        if not trades:
            label = f" for {ticker.upper()}" if ticker else ""
            return f"No trades found{label}."

        label = f" — {ticker.upper()}" if ticker else ""
        lines = [f"Trade History{label}", "─" * 48]
        for t in trades:
            stamp = fmt_sgt(t.traded_at)
            lines.append(
                f"{stamp}  {t.side.value:<4} {t.shares:>10,.4f} {t.ticker:<8} "
                f"@ ${t.price:>10,.2f}  (${t.gross_value:>12,.2f})"
            )
        return "\n".join(lines)

    def pending_orders_report(self) -> str:
        """Return all pending and confirmed orders."""
        orders: list[Order] = (
            self._db.query(Order)
            .filter(Order.status.in_([OrderStatus.PENDING, OrderStatus.CONFIRMED]))
            .order_by(Order.created_at)
            .all()
        )
        if not orders:
            return "No pending orders."
        lines = ["Pending Orders", "─" * 40]
        for o in orders:
            price = f"${o.limit_price:,.2f}" if o.limit_price else "MKT"
            lines.append(
                f"#{o.id:<5} {o.status.value:<12} {o.side.value} "
                f"{o.shares} {o.ticker} @ {price}"
            )
        return "\n".join(lines)
