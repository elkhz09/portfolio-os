# Portfolio OS

A paper-trading system for running a discretionary portfolio: you decide, it
records, checks and reports. Commands go in over Telegram or the CLI, orders sit
as `PENDING` until confirmed, and every fill lands in a SQLite ledger with its
rationale attached.

The system never picks an investment or reallocates on its own. There is no
signal, no model, no automation of the decision. What is automated is the
bookkeeping around the decision, which is the part I kept getting wrong by hand.

---

## Why it exists

Running a portfolio by hand means a spreadsheet that drifts out of date, trades
recorded in three places, and no honest record of why a position was opened.
This covers that layer: one ledger, one P&L calculation, pre-trade checks that
run before you can confirm, and a thesis field that is part of the order rather
than a note somewhere else.

---

## What works

- **Command parser** — strict grammar, Pydantic-validated, rejects malformed
  orders rather than guessing.
- **Portfolio state** — positions, target weights, drift against target.
- **Rebalance** — computes drift and stages the orders that would close it.
- **Pre-trade risk checks** — cash available, position limit, tradable
  allowlist, duplicate order detection. All run before confirmation.
- **Paper execution** — `PENDING` → `CONFIRMED` → `EXECUTED`, each transition
  timestamped.
- **FIFO realised P&L** — lot-level, across partial sells.
- **Reports** — portfolio, trades, journal and audit log as text.
- **Interfaces** — Telegram bot and a Streamlit dashboard.

181 tests, covering the parser, risk checks, FIFO accounting, rebalance maths,
execution state machine and settings parsing.

## What does not

- No broker integration. Nothing reaches a real market.
- No price feed. Unrealised P&L uses the price you supply, so marks are only as
  fresh as your last input.
- No benchmark comparison, attribution or tax lots beyond FIFO.
- Single user, single currency, single base portfolio.

---

## Commands

| Command | Description |
|---|---|
| `/buy TICKER SIZE [PRICE] --thesis "..."` | Queue a buy with optional rationale |
| `/sell TICKER SIZE [PRICE]` | Queue a sell |
| `/confirm ID` | Execute a pending order |
| `/weight TICKER PCT` | Set target allocation |
| `/rebalance` | Compute drift vs targets, stage rebalance orders |
| `/pnl` | Realised and unrealised P&L |
| `/status` | Portfolio snapshot |
| `/journal` | View or add thesis entries |

---

## Layout

```
app/
  config/       settings and allowlist (pydantic-settings)
  db/           SQLAlchemy models, cash ledger, seed script
  parser/       command parser and schemas
  portfolio/    state, weights, drift, rebalance
  execution/    paper execution engine
  risk/         pre-trade checks
  analytics/    FIFO P&L, metrics
  reports/      text report generators
  interface/    Telegram bot, Streamlit dashboard
tests/
main.py         CLI entrypoint
docs/           architecture and MVP scope notes
```

Python 3.11+, SQLite, SQLAlchemy, Pydantic, Streamlit, python-telegram-bot.

---

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py initdb
python -m app.db.seed --cash 100000
python main.py status
```

That much works with the `.env.example` defaults and no Telegram token. For the
bot, put a BotFather token and your Telegram user ID in `.env`, then:

```bash
python main.py bot
streamlit run app/interface/dashboard.py   # separate terminal
```

Paper mode is on by default (`PAPER_MODE=true`).

---

## Design notes

- Orders are never executed on arrival. `/confirm` is a separate step with its
  own order ID, so a mistyped size is recoverable.
- Risk checks run when the order is entered, so a failing order is rejected
  before it is ever staged. They are not re-run at `/confirm`, which means a
  pending order confirmed much later is checked against the cash position as it
  was at entry. Single user and short-lived orders make that survivable, but it
  is a real gap rather than a deliberate choice.
- The cash ledger is append-only. Each row stores the balance after it, and the
  current balance is read from the latest row rather than recomputed.
- Every trade carries a timestamp, a user ID and the thesis given at order time.

---

## Possible extensions

Broker API integration and a price feed are the two things that would make this
usable against a live account. Benchmark comparison and attribution would make
the reporting worth reading. Neither is built, and I would rather say so than
list them as a roadmap.

MIT licensed.
