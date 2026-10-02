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

Python 3.11+, SQLAlchemy, Pydantic, python-telegram-bot, Streamlit. 2,300 lines
of application code, 1,650 of tests.

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
  warning. A failing check stops the order being created at all, and the same
  checks run again at `/confirm` against the position as it is then.
- **One price resolver, and it is allowed to refuse.** The policy is *fetch, or
  use what is known, or refuse — never invent*: an explicit limit price, else
  the last marked price, else the average cost actually paid, else the order is
  declined. Nothing fills at a placeholder.
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

158 tests, all passing, most recently on Python 3.14. Every one of them covers
code that runs. That number used to be 181; 67 of those defended a module that
was never on the execution path, and deleting it was worth more than the count.

| Area | Tests | What breaks without them |
|---|---|---|
| Models, ledger, reports | 33 | balance arithmetic, report rendering |
| Risk checks | 25 | selling more than held, duplicate orders, cash limits, unpriced orders |
| Command parser | 22 | malformed orders being accepted |
| Execution | 18 | weighted average cost, cash direction, state guards |
| `/confirm` pricing and re-checks | 18 | filling at a guessed price, confirming against stale cash |
| Price resolution | 14 | a fabricated price reaching the ledger |
| Settings parsing | 10 | startup aborting on a comma-separated env var |
| Rebalance | 9 | drift sizing, sell-before-buy ordering, unpriced tickers |
| FIFO | 9 | lot ordering across partial sells |

## What was hard

Four things, none of them the Telegram part.

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
Checks at confirm are the ones that are actually true, because the cash and the
position can both move in between. The code now does both. The thing that made
that awkward is that at confirm the order is already on the book, so it reads as
its own duplicate and counts against its own open-order limit — `check_order`
takes an `exclude_order_id` for exactly that, and two tests exist only to pin
that excluding it does not quietly disable the checks it is excluded from.

**Having one answer to "what does this fill at".** There is no price feed, so
the price has to come from a limit price or from something already recorded. The
risk layer and the bot each worked that out separately, and they drifted into
disagreeing: the risk checks skipped the cash test on a market order, while the
bot filled a never-held ticker at $1.00. Both now call one resolver that returns
a price or a refusal, which is the only reason the two can no longer diverge.

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

Leaving `PRICE` off means "use what you already know about this ticker". If
nothing is known the order is refused and tells you to set a `/price` or give a
limit — it is never filled at a guess.
| `/confirm ID` / `/cancel ID` | Execute or drop a pending order |
| `/price TICKER VALUE` | Set the last known price, used for marks and fills |
| `/weight TICKER 0.XX` | Set a target allocation |
| `/rebalance` | Compute drift against targets and stage orders |
| `/status` `/pnl` `/history` `/journal` `/risk` | Read the state |

---

## What it does not do

- No broker integration. Nothing reaches a real market.
- No price feed. Marks are as fresh as the last `/price` you typed, and an order
  on a ticker you have never priced is declined rather than guessed at. If a feed
  is ever added it belongs in `app/portfolio/pricing.py` and nowhere else.
- Single user, single currency, one portfolio, no benchmark or attribution.
- FIFO only. Not tax accounting, and no cost-basis elections.

## Where it is thin, specifically

These are checked against the code rather than remembered, and they are the
answers to the questions worth asking about it.

**A refused order gives you no way to see the price it was refused for.** The
refusal names the remedy (`/price TICKER VALUE`) but not what the system
currently thinks the ticker is worth, because it thinks nothing. Checking means
running `/status`.

**The price resolver has no feed, so its first tier is you.** "Fetch, or use what
is known, or refuse" is three tiers on paper and two in practice: there is no
fetch. A `/price` from last week counts as known and an order is checked and
filled against it without complaint. The holdings row has an `updated_at`, but it
moves on any change to the row including a trade, so it is not the age of the
price and nothing reads it as one. Refusing to guess is not the same as knowing
the mark is current.

**Re-checking at `/confirm` is not a lock.** It closes the window between entry
and confirm, which is where the real risk was. It does not make confirm atomic —
there is one user and one process, so nothing else is writing, and that is the
only reason it holds.

**In paper mode `/confirm` confirms and executes in one step,** so `CONFIRMED` is
a state the database records but a user never sees. The three-state machine is
real in the code and effectively two states in use.

**`/rebalance` drops orders that fail their risk check without saying which.**
It reports the count it staged. If three of five were refused you are not told
that, only that two exist.

## What went wrong building it

**Two parsers existed and only one was wired in.** `app/parser/instructions.py`
was a 449-line Pydantic schema set with more tests behind it than any other file
here — 67 of what was then 181. The bot imports `app/parser/command_parser.py`,
which is regex and `shlex`. Nothing constructed an `Instruction`, so the headline
test count was better than the coverage it implied. It is deleted. The test count
went 181 to 151, which reads worse and is worth more; the re-checking work above
took it to 158.

Worth recording from the deletion: the dead module was not inert. The package
`__init__` re-exported it, so it was imported and its Pydantic models built on
every bot startup, for nothing. And mutating the live parser while reviewing the
deletion turned up a gap the 67 deleted tests never covered either — zero size
and zero limit price had no test on the parser that actually runs. Three were
added, plus one pinning the package surface so the dead layer cannot return
unnoticed.

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
  parser/       command_parser.py — regex and shlex, strict
  portfolio/    holdings, weights, drift, rebalance, price resolution
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
overstate how close they are. The feed at least has a defined place to land now:
one function, with one caller shape, that is already allowed to say no.

MIT licensed.
