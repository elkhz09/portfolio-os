# Portfolio OS

Portfolio OS is a paper-trading system for a portfolio you run yourself: you
decide, it records, checks and reports. It runs as a Telegram bot over a SQLite
database, and almost all of it is the bookkeeping that is easy to get wrong by
hand: an append-only cash ledger, FIFO realised P&L across partial sells,
pre-trade risk checks that block an order before it is staged, and a state
machine where nothing executes until you confirm it.

It never picks an investment or reallocates on its own. There is no signal and no
model. What is automated is the accounting around a decision, which is the part I
kept getting wrong in a spreadsheet.

Python 3.11+, SQLAlchemy, Pydantic, python-telegram-bot, Streamlit. 2,700 lines
of application code, 1,500 of tests.

---

## What it does

Orders go in as text and come back as state you can query.

```
/buy NVDA 50 180 --thesis datacentre capex still accelerating
  -> risk checks run; order #7 queued PENDING
/confirm 7
  -> filled, cash ledger debited, holding updated, audit row written
/pnl
  -> realised P&L by FIFO lot, unrealised against your last marked price
```

- **Command parser.** One grammar, strict. A malformed order raises rather than
  guessing what you meant. `/buy AAPL` with no size is an error, not a default.
- **Pre-trade risk checks.** Tradable allowlist, duplicate open order, open order
  count, position size, no short selling, cash sufficiency, concentration
  warning. A failing check stops the order being created at all.
- **Append-only cash ledger.** Every movement is a row that stores the balance
  after it. The current balance is read from the last row rather than recomputed,
  so there is one number and a history of how it got there.
- **FIFO realised P&L.** Lot queue per ticker, consumed front-first, correct
  across partial sells and multiple sell legs.
- **Order state machine.** `PENDING` to `CONFIRMED` to `EXECUTED`, each
  transition timestamped and written to an audit log with the Telegram user ID.
- **Target weights and rebalance.** Set target allocations, compute drift
  against them, stage the orders that would close it. Sells are staged before
  buys so the buys have cash.
- **Two interfaces.** Telegram for input, Streamlit for looking at it.

### What the tests actually protect

181 tests, all passing, most recently on Python 3.14.

| Area | Tests | What breaks without them |
|---|---|---|
| Pydantic instruction schema | 67 | see the note below, this module is not on the live path |
| Models, ledger, reports | 33 | balance arithmetic, report rendering |
| Live command parser | 18 | malformed orders being accepted |
| Execution | 18 | weighted average cost, cash direction, state guards |
| Risk checks | 17 | selling more than held, duplicate orders, cash limits |
| Settings parsing | 10 | startup aborting on a comma-separated env var |
| Rebalance | 9 | drift sizing, sell-before-buy ordering, unpriced tickers |
| FIFO | 9 | lot ordering across partial sells |

## What was hard

Three things, none of them the Telegram part.

**Realised P&L across partial sells.** Selling half a position twice, from lots
bought at different prices, has one right answer and several plausible wrong ones,
and the wrong ones agree with the right one on every simple case. The tests that
earn their place are the ones with two lots at different prices and two sell legs,
because those are the only shape that separates FIFO from taking everything off
the front lot.

**Keeping one truth about cash.** Cash is needed in the risk checks, the execution
path, the rebalance sizing, the metrics and the reports. Recomputing it in each is
how two of them end up disagreeing, so all six call sites read it from the ledger
through one function and nothing else touches the balance.

**Deciding when a check runs.** Checks at order entry are cheap and catch typos.
Checks at execution are the ones that are actually true. The code does the
former, which is a real limitation rather than a resolved question. See below.

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

That works on the `.env.example` defaults with no Telegram token and no network.
For the bot, put a BotFather token and your own Telegram user ID in `.env`:

```bash
python main.py bot
streamlit run app/interface/dashboard.py   # separate terminal
```

Paper mode is on by default. Leaving `TELEGRAM_ALLOWED_USER_IDS` empty means
anyone who finds the bot can use it, so set it.

### Commands

| Command | Description |
|---|---|
| `/buy TICKER SIZE [PRICE] [--thesis ...]` | Queue a buy, with the reason attached |
| `/sell TICKER SIZE [PRICE]` | Queue a sell |
| `/confirm ID` / `/cancel ID` | Execute or drop a pending order |
| `/price TICKER VALUE` | Set the last known price, used for marks and fills |
| `/weight TICKER 0.XX` | Set a target allocation |
| `/rebalance` | Compute drift against targets and stage orders |
| `/status` `/pnl` `/history` `/journal` `/risk` | Read the state |

---

## What it does not do

- No broker integration. Nothing reaches a real market.
- No price feed. Marks are as fresh as the last `/price` you typed.
- Single user, single currency, one portfolio, no benchmark or attribution.
- FIFO only. Not tax accounting, and no cost-basis elections.

## Where it is thin, specifically

These are checked against the code rather than remembered, and they are the
answers to the questions worth asking about it.

**Risk checks run at order entry and are not re-run at `/confirm`.** An order
confirmed much later is being confirmed against the cash position as it was when
it was entered. One user and short-lived orders make that survivable. It is still
a gap, not a design choice.

**The cash check only runs when you give a limit price.** `/buy NVDA 50 180` is
checked against cash. `/buy NVDA 50` is not, because without a price there is
nothing to check against, and nothing substitutes the last known price in. A
market order of 50,000 shares passes every check on a $100,000 account.

**A market order on a ticker with no price set fills at $1.00.** The paper fill
falls back to the last marked price, then the average cost, then to 1.0. The last
step is a placeholder that should refuse instead. Set `/price` first.

**In paper mode `/confirm` confirms and executes in one step,** so `CONFIRMED` is
a state the database records but a user never sees. The three-state machine is
real in the code and effectively two states in use.

**`/rebalance` drops orders that fail their risk check without saying which.**
It reports the count it staged. If three of five were refused you are not told
that, only that two exist.

## What went wrong building it

**Two parsers exist and only one is wired in.** `app/parser/instructions.py` is a
Pydantic schema set, 449 lines, with more tests behind it than any other file here.
The bot imports `app/parser/command_parser.py`, which is regex and `shlex`.
Nothing on the runtime path imports the Pydantic layer. So 67 of the 181 tests
cover a module that never runs, and the headline test count is better than the
coverage it implies. Either wiring it in or deleting it would be an improvement.
Neither has happened.

**Startup broke on a comma-separated environment variable.** `TRADABLE_ALLOWLIST=AAPL,SPY`
aborted the process. `pydantic-settings` JSON-decodes list and set fields in the
source layer, before any validator runs, so a bare `AAPL,SPY` is a parse failure
and a bare `123` silently becomes an integer. The fix is `NoDecode` on the
annotation plus a `mode="before"` validator that accepts both forms, and ten
tests that pin it. Two commits in this repository are that single bug.

---

## Layout

```
app/
  config/       settings and allowlist (pydantic-settings)
  db/           SQLAlchemy models, cash ledger, seed
  parser/       command_parser.py is live; instructions.py is not
  portfolio/    holdings, weights, drift, rebalance
  execution/    paper execution and the state machine
  risk/         pre-trade checks
  analytics/    FIFO P&L, metrics
  reports/      text report generators
  interface/    Telegram bot, Streamlit dashboard
tests/
main.py         CLI entrypoint
docs/           early architecture and scope notes, kept as written
```

A broker API and a price feed are the two things that would make this usable
against a real account. Neither is built, and listing them as a roadmap would
overstate how close they are.

MIT licensed.
