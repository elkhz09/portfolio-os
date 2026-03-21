"""Telegram bot interface.

All commands are routed through the strict parser. No order is executed
without an explicit /confirm from the user.
"""

import logging
from datetime import datetime

from loguru import logger
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from app.config import get_settings
from app.db.models import AuditLog, Holding, Order, OrderSide, OrderStatus, TargetAllocation, ThesisEntry
from app.db.session import SessionLocal
from app.execution.paper_engine import ExecutionError, PaperEngine
from app.parser.command_parser import CommandName, ParseError, parse_command
from app.portfolio.state import PortfolioState
from app.reports.generator import ReportGenerator
from app.risk.checks import RiskChecker

settings = get_settings()

# Suppress noisy telegram library logs
logging.getLogger("httpx").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def _is_allowed(update: Update) -> bool:
    if not settings.telegram_allowed_user_ids:
        return True  # open if no allowlist configured
    return update.effective_user.id in settings.telegram_allowed_user_ids


async def _deny(update: Update) -> None:
    await update.message.reply_text("⛔ Unauthorised.")


# ---------------------------------------------------------------------------
# Unified dispatcher
# ---------------------------------------------------------------------------

async def dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parse and dispatch any /<command> message."""
    if not _is_allowed(update):
        await _deny(update)
        return

    text = update.message.text or ""
    user_id = update.effective_user.id

    try:
        cmd = parse_command(text)
    except ParseError as exc:
        await update.message.reply_text(f"❌ Parse error: {exc}")
        return

    with SessionLocal() as db:
        reporter = ReportGenerator(db)
        state = PortfolioState(db)
        engine = PaperEngine(db, state)
        risk = RiskChecker(db)

        try:
            reply = await _handle(cmd.name, cmd.args, db, reporter, engine, risk, user_id)
        except ExecutionError as exc:
            reply = f"🚫 Execution error: {exc}"
        except Exception as exc:
            logger.exception("Unhandled error in bot dispatch")
            reply = f"💥 Unexpected error: {exc}"

    await update.message.reply_text(reply, parse_mode=None)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def _handle(name, args, db, reporter, engine, risk, user_id: int) -> str:
    match name:
        case CommandName.START:
            return (
                "👋 Portfolio OS — paper trading, you decide everything.\n"
                "\n"
                "── TYPICAL FLOW ──────────────────\n"
                "/price SPY 512          set last price\n"
                "/weight SPY 0.40        set 40% target\n"
                "/rebalance              queue drift orders\n"
                "/confirm 1              execute order #1\n"
                "/status                 check portfolio\n"
                "\n"
                "── PORTFOLIO ─────────────────────\n"
                "/status                 all positions + cash\n"
                "/pnl                    realised + unrealised P&L\n"
                "/price TICKER VALUE     update last known price\n"
                "\n"
                "── ORDERS ────────────────────────\n"
                "/buy TICKER SIZE [PRICE] [--thesis note]\n"
                "/sell TICKER SIZE [PRICE]\n"
                "  → nothing executes until you /confirm\n"
                "/confirm ID             execute pending order\n"
                "/cancel ID              cancel pending order\n"
                "\n"
                "── ALLOCATION ────────────────────\n"
                "/weight TICKER 0.XX     set target weight\n"
                "  e.g. /weight GLD 0.05 = 5% of AUM\n"
                "/rebalance              compute + queue buy/sells to hit targets\n"
                "  sells queued first to free cash, then buys\n"
                "  skips tickers with no price set\n"
                "\n"
                "── HISTORY & JOURNAL ─────────────\n"
                "/history                last 30 executed trades\n"
                "/history TICKER         filtered to one ticker\n"
                "/journal                all thesis notes\n"
                "/journal add TICKER note text here\n"
                "/journal add note text here (no ticker)\n"
                "  also auto-saved when you use --thesis on a buy\n"
                "/risk                   recent audit log\n"
                "\n"
                "── RULES ─────────────────────────\n"
                "• All orders start PENDING — /confirm to execute\n"
                "• System never picks investments or rebalances automatically\n"
                "• Every action is logged with timestamp + user ID\n"
            )

        case CommandName.STATUS | CommandName.POSITIONS:
            return reporter.portfolio_summary()

        case CommandName.PNL:
            return reporter.pnl_report()

        case CommandName.RISK:
            return reporter.audit_tail(limit=10)

        case CommandName.BUY | CommandName.SELL:
            side = OrderSide.BUY if name == CommandName.BUY else OrderSide.SELL
            ticker = args["ticker"]
            shares = args["size"]
            limit_price = args.get("limit_price")
            thesis_text = args.get("thesis")

            result = risk.check_order(ticker, side, shares, limit_price)
            if not result.passed:
                return f"🚫 Risk check failed:\n{result.summary}"

            order = Order(
                ticker=ticker,
                side=side,
                shares=shares,
                limit_price=limit_price,
                thesis=thesis_text,
                status=OrderStatus.PENDING,
                paper=settings.paper_mode,
                telegram_user_id=user_id,
            )
            db.add(order)
            if thesis_text:
                db.add(ThesisEntry(
                    ticker=ticker,
                    body=thesis_text,
                    telegram_user_id=user_id,
                    created_at=datetime.utcnow(),
                ))
            db.commit()
            db.refresh(order)

            price_str = f"${limit_price:,.2f}" if limit_price else "market"
            warn_str = f"\n{result.summary}" if result.warnings else ""
            return (
                f"📋 Order #{order.id} queued (PENDING)\n"
                f"{side.value} {shares} {ticker} @ {price_str}\n"
                f"{'📝 ' + thesis_text if thesis_text else ''}"
                f"{warn_str}\n\n"
                f"Reply /confirm {order.id} to execute or /cancel {order.id} to abort."
            )

        case CommandName.CONFIRM:
            order_id = args["order_id"]
            order = engine.confirm_order(order_id, user_id)
            if settings.paper_mode:
                holding = db.query(Holding).filter_by(ticker=order.ticker).first()
                sim_price = (holding.last_price or holding.avg_cost) if holding else 1.0
                if sim_price == 0:
                    sim_price = 1.0
                trade = engine.execute_order(order_id, market_price=sim_price)
                return (
                    f"✅ Paper trade executed\n"
                    f"#{order_id} {order.side.value} {order.shares} "
                    f"{order.ticker} @ ${trade.price:,.2f}"
                )
            return f"✅ Order #{order_id} confirmed. Awaiting execution."

        case CommandName.CANCEL:
            order_id = args["order_id"]
            engine.cancel_order(order_id, user_id)
            return f"🗑 Order #{order_id} cancelled."

        case CommandName.REBALANCE:
            from app.portfolio.rebalance import compute_rebalance_trades
            trades = compute_rebalance_trades(db)
            if not trades:
                return (
                    "✅ Portfolio is already aligned with targets, "
                    "or no target allocations have been set.\n"
                    "Use /weight TICKER 0.XX to set targets."
                )
            orders_created = []
            for rt in trades:
                risk_result = risk.check_order(rt.ticker, rt.side, rt.shares)
                if not risk_result.passed:
                    continue
                order = Order(
                    ticker=rt.ticker,
                    side=rt.side,
                    shares=rt.shares,
                    status=OrderStatus.PENDING,
                    paper=settings.paper_mode,
                    telegram_user_id=user_id,
                )
                db.add(order)
                orders_created.append((rt, order))
            if not orders_created:
                return "🚫 All rebalance orders failed risk checks."
            db.commit()
            lines = [f"📊 Rebalance — {len(orders_created)} order(s) queued:"]
            for rt, order in orders_created:
                db.refresh(order)
                lines.append(
                    f"  #{order.id} {rt.side.value} {rt.shares:.4f} "
                    f"{rt.ticker} ~${rt.estimated_price:,.2f}/sh"
                )
            lines.append("\nConfirm each with /confirm <id> or cancel with /cancel <id>.")
            return "\n".join(lines)

        case CommandName.WEIGHT:
            ticker = args["ticker"]
            weight = args["weight"]
            existing = db.query(TargetAllocation).filter_by(ticker=ticker).first()
            if existing:
                old = existing.target_weight
                existing.target_weight = weight
                existing.set_at = datetime.utcnow()
                existing.set_by_user_id = user_id
                db.commit()
                return (
                    f"🎯 Target updated: {ticker} {old:.1%} → {weight:.1%}\n"
                    f"Run /rebalance to generate orders."
                )
            db.add(TargetAllocation(
                ticker=ticker,
                target_weight=weight,
                set_by_user_id=user_id,
            ))
            db.commit()
            return (
                f"🎯 Target set: {ticker} = {weight:.1%}\n"
                f"Run /rebalance to generate orders."
            )

        case CommandName.HISTORY:
            ticker = args.get("ticker")
            return reporter.trade_history_report(ticker=ticker)

        case CommandName.PRICE:
            ticker = args["ticker"]
            price = args["price"]
            holding = db.query(Holding).filter_by(ticker=ticker).first()
            if holding is None:
                holding = Holding(ticker=ticker, shares=0.0, avg_cost=0.0, last_price=price)
                db.add(holding)
            else:
                holding.last_price = price
            db.add(AuditLog(
                event="PRICE_UPDATED",
                detail=f"{ticker}={price}",
                telegram_user_id=user_id,
            ))
            db.commit()
            return f"💹 {ticker} last price set to ${price:,.2f}"

        case CommandName.JOURNAL:
            subcommand = args.get("subcommand", "list")
            if subcommand == "list":
                return reporter.journal_report()
            elif subcommand == "add":
                note = args["note"]
                ticker = args.get("ticker")
                entry = ThesisEntry(
                    ticker=ticker,
                    body=note,
                    telegram_user_id=user_id,
                    created_at=datetime.utcnow(),
                )
                db.add(entry)
                db.commit()
                tag = f"[{ticker}] " if ticker else ""
                return f"📝 Journal entry saved: {tag}{note}"

        case _:
            return f"Unhandled command: {name}"

    return "Done."


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run_bot() -> None:
    """Start the Telegram bot (blocking)."""
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    app = Application.builder().token(token).build()

    for cmd_name in CommandName:
        app.add_handler(CommandHandler(cmd_name.value, dispatch))

    mode = "PAPER" if settings.paper_mode else "LIVE"
    logger.info("Starting Portfolio OS bot [{} mode]", mode)
    app.run_polling(drop_pending_updates=True)
