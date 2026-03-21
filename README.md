# Portfolio OS
**MVP 1 — human-in-the-loop discretionary macro portfolio management system**

> The system never makes investment decisions. The user is always the decision-maker.

The core PM workflow is operational. Integration layer (live broker API, external data feeds) and planned ML extensions are not yet built — this is a paper trading system in active development.

---

## What This Project Demonstrates

Built to reflect how a discretionary PM workflow actually operates — not just data analysis, but the full operational stack:

- **Portfolio construction logic** — target weight setting, drift computation, rebalance order generation
- **Risk controls** — pre-trade checks for cash availability, position limits, tradable allowlist, duplicate prevention
- **P&L accounting** — FIFO realised P&L tracking across all trades
- **Audit discipline** — every order requires explicit confirmation; every action is logged with timestamp and thesis
- **Reporting** — Streamlit dashboard with allocation breakdown and P&L charts; text reports via Telegram

---

## System Design

```
app/
  config/       environment settings and allowlist (Pydantic)
  db/           SQLAlchemy models, cash ledger, seed script
  parser/       strict command parser + Pydantic schema validation
  portfolio/    state engine, weight/drift computation, rebalance logic
  execution/    paper execution engine (PENDING → CONFIRMED → EXECUTED)
  risk/         pre-trade checks (cash, allowlist, duplicate, position limit)
  analytics/    FIFO P&L, portfolio metrics
  reports/      text report generators (portfolio, trades, journal, audit)
  interface/    Telegram bot, Streamlit dashboard
tests/
main.py         CLI entrypoint
```

Stack: Python 3.11 · SQLite · SQLAlchemy · Pydantic · Streamlit · python-telegram-bot

---

## Command Interface

| Command | Description |
|---|---|
| `/buy TICKER SIZE [PRICE] --thesis "..."` | Queue a buy with optional rationale |
| `/sell TICKER SIZE [PRICE]` | Queue a sell |
| `/confirm ID` | Execute a pending order |
| `/weight TICKER PCT` | Set target allocation |
| `/rebalance` | Compute drift vs targets, stage rebalance orders |
| `/pnl` | Realised + unrealised P&L |
| `/status` | Portfolio snapshot |
| `/journal` | View or add thesis entries |

---

## Key Design Principles

- All orders start `PENDING` and require `/confirm` — nothing executes automatically
- Paper mode is the default (`PAPER_MODE=true`)
- Every trade is logged with timestamp, thesis, and user ID
- The system never selects investments or reallocates without instruction

---

## Roadmap

**MVP 1 — complete**
- Command interface, parser, portfolio state engine, paper execution, risk checks, FIFO P&L, Streamlit dashboard, Telegram bot, unit tests

**MVP 2 — planned**
- Live broker API integration
- External price feed integration
- Enhanced analytics and benchmark comparison

**MVP 3 — planned**
- ML-assisted thesis tagging and pattern analysis
- Automated performance attribution

---

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add Telegram bot token and user ID
python main.py initdb
python -m app.db.seed --cash 100000
python main.py bot
# separate terminal:
streamlit run app/interface/dashboard.py
```
