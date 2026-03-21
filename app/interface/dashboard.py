"""Streamlit dashboard — run with: streamlit run app/interface/dashboard.py"""

import sys
from pathlib import Path

# Ensure project root is on sys.path when Streamlit runs the script directly
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.utils.time import fmt_sgt

from app.analytics.metrics import PortfolioMetrics
from app.db.models import CashLedger, TargetAllocation
from app.db.session import SessionLocal
from app.portfolio.state import PortfolioState
from app.reports.generator import ReportGenerator

st.set_page_config(page_title="Portfolio OS", layout="wide")
st.title("Portfolio OS")
st.caption("Human-in-the-loop discretionary macro portfolio · paper mode")

with SessionLocal() as db:
    reporter = ReportGenerator(db)
    metrics = PortfolioMetrics(db)
    state = PortfolioState(db)

    pnl = metrics.pnl_summary()
    holdings = state.all_holdings()
    weights = state.compute_weights()
    targets = {t.ticker: t.target_weight for t in db.query(TargetAllocation).all()}

    # ── Top-line metrics ──────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total AUM", f"${state.total_aum():,.0f}")
    c2.metric("Market Value", f"${pnl.total_market_value:,.0f}")
    c3.metric("Cash", f"${pnl.cash_balance:,.0f}")
    c4.metric("Unrealised P&L", f"${pnl.unrealised_pnl:+,.0f}")
    c5.metric("Realised P&L", f"${pnl.realised_pnl:+,.0f}")

    st.divider()

    # ── Charts row ────────────────────────────────────────────────────────────
    chart_col, pnl_col = st.columns(2)

    with chart_col:
        st.subheader("Allocation")
        if holdings or pnl.cash_balance > 0:
            alloc_labels = [h.ticker for h in holdings] + ["CASH"]
            alloc_values = [
                (h.market_value or h.shares * h.avg_cost) for h in holdings
            ] + [pnl.cash_balance]

            # Build target trace for comparison
            target_values = [targets.get(h.ticker, 0.0) for h in holdings] + [0.0]
            aum = state.total_aum()
            target_dollar = [v * aum for v in target_values]

            fig = go.Figure()
            fig.add_trace(go.Bar(
                name="Current ($)",
                x=alloc_labels,
                y=alloc_values,
                marker_color="#4C9BE8",
            ))
            fig.add_trace(go.Bar(
                name="Target ($)",
                x=alloc_labels,
                y=target_dollar,
                marker_color="#E8A84C",
                opacity=0.6,
            ))
            fig.update_layout(
                barmode="group",
                height=320,
                margin=dict(l=0, r=0, t=0, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                yaxis_tickprefix="$",
                yaxis_tickformat=",.0f",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No holdings to chart.")

    with pnl_col:
        st.subheader("Unrealised P&L by Holding")
        pnl_holdings = [h for h in holdings if h.unrealised_pnl is not None]
        if pnl_holdings:
            pnl_df = pd.DataFrame({
                "Ticker": [h.ticker for h in pnl_holdings],
                "uPnL": [h.unrealised_pnl for h in pnl_holdings],
            })
            colors = ["#2ECC71" if v >= 0 else "#E74C3C" for v in pnl_df["uPnL"]]
            fig2 = px.bar(
                pnl_df, x="Ticker", y="uPnL",
                color="uPnL",
                color_continuous_scale=["#E74C3C", "#2ECC71"],
                labels={"uPnL": "Unrealised P&L ($)"},
            )
            fig2.update_layout(
                height=320,
                margin=dict(l=0, r=0, t=0, b=0),
                coloraxis_showscale=False,
                yaxis_tickprefix="$",
                yaxis_tickformat=",.0f",
            )
            fig2.add_hline(y=0, line_dash="dash", line_color="grey", line_width=1)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No price data for unrealised P&L. Use /price TICKER VALUE to set prices.")

    st.divider()

    # ── Holdings table ────────────────────────────────────────────────────────
    st.subheader("Holdings")
    if holdings:
        aum = state.total_aum()
        rows = []
        for h in holdings:
            current_w = weights.get(h.ticker, 0.0)
            target_w = targets.get(h.ticker)
            drift = (current_w - target_w) if target_w is not None else None
            rows.append({
                "Ticker": h.ticker,
                "Shares": f"{h.shares:,.4f}",
                "Avg Cost": f"${h.avg_cost:,.2f}",
                "Last Price": f"${h.last_price:,.2f}" if h.last_price else "—",
                "Mkt Value": f"${h.market_value:,.2f}" if h.market_value else "—",
                "Weight": f"{current_w:.1%}",
                "Target": f"{target_w:.1%}" if target_w is not None else "—",
                "Drift": f"{drift:+.1%}" if drift is not None else "—",
                "uPnL": f"${h.unrealised_pnl:+,.2f}" if h.unrealised_pnl is not None else "—",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No holdings. Use /buy from Telegram to open positions.")

    st.divider()

    # ── Two-column bottom section ─────────────────────────────────────────────
    left, right = st.columns(2)

    with left:
        st.subheader("Pending Orders")
        st.text(reporter.pending_orders_report())

        st.subheader("Recent Trades")
        st.text(reporter.trade_history_report(limit=10))

    with right:
        st.subheader("Cash Ledger")
        ledger_rows = (
            db.query(CashLedger)
            .order_by(CashLedger.occurred_at.desc())
            .limit(15)
            .all()
        )
        if ledger_rows:
            ledger_data = [
                {
                    "Date": fmt_sgt(r.occurred_at),
                    "Type": r.entry_type.value,
                    "Amount": f"${r.amount:+,.2f}",
                    "Balance": f"${r.balance_after:,.2f}",
                    "Note": r.note or "",
                }
                for r in ledger_rows
            ]
            st.dataframe(pd.DataFrame(ledger_data), use_container_width=True, hide_index=True)
        else:
            st.info("No cash entries.")

        st.subheader("Thesis Journal")
        st.text(reporter.journal_report(limit=8))

    st.divider()

    with st.expander("Audit Log (last 50 events)"):
        st.text(reporter.audit_tail(limit=50))
