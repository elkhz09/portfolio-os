# Portfolio OS — MVP Scope

## Objective

Build a working system that:

- accepts structured instructions
- simulates execution
- tracks portfolio state
- logs decisions
- displays performance

---

## MVP Features

### 1. Command Interface

- Telegram bot
- commands:
  - /buy
  - /sell
  - /set_target
  - /rebalance
  - /portfolio
  - /history
  - /thesis

---

### 2. Command Parser

- structured schema
- validation
- error handling

---

### 3. Portfolio Engine

- track holdings
- track cash
- compute weights
- support target allocation
- generate rebalance logic

---

### 4. Paper Execution Engine

- simulate trades
- update holdings
- update cash
- log orders and trades

---

### 5. Database

- SQLite
- tables:
  - holdings
  - trades
  - orders
  - thesis_entries
  - cash

---

### 6. Thesis Logging

- manual input
- store rationale

---

### 7. Dashboard

Display:

- portfolio value
- holdings
- weights
- cash
- PnL
- trade history

---

### 8. Testing

- parser tests
- execution tests

---

## Exclusions (Do NOT build yet)

- live trading
- IBKR integration
- AI decision-making
- complex risk models
- auto social posting
- multi-account support

---

## Success Criteria

System is successful if:

- commands update portfolio correctly
- trades are logged
- dashboard reflects state accurately
- system is stable and understandable

---

## Development Phases

### Phase 1
- parser
- database
- execution

### Phase 2
- Telegram interface
- portfolio engine improvements

### Phase 3
- dashboard
- analytics

### Phase 4 (Post-MVP)
- IBKR integration
- risk rules
- recurring trades
- content generation

---

## Guiding Principle

Do not optimize for features.

Optimize for:

- clarity
- correctness
- extensibility