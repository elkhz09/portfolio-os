# Portfolio OS — Architecture

## Overview

Portfolio OS is a human-driven portfolio management system with automated execution, tracking, and analytics.

The system separates:

- Decision-making → human
- Execution and tracking → system

---

## System Flow

User → Interface → Parser → Validator → Portfolio Engine → Execution → Database → Analytics → Dashboard

---

## Core Components

### 1. Interface Layer

Handles:
- user commands
- responses

Example commands:
- /buy
- /sell
- /set_target
- /rebalance
- /portfolio

Output:
- raw input → structured instruction

---

### 2. Parser Layer

Converts user input into structured format.

Example:

    Input: /buy 100 AAPL

    Output:
        action: buy_shares
        ticker: AAPL
        quantity: 100

Responsibilities:
- parse commands
- normalize values
- basic validation

---

### 3. Validation & Risk Layer

Ensures instruction is safe.

Checks:
- ticker validity
- sufficient cash
- sufficient shares
- position limits
- allocation limits
- duplicate orders

Outputs:
- approved
- rejected
- requires confirmation

---

### 4. Portfolio State Engine

Tracks full portfolio state.

Includes:
- holdings
- cash
- target allocations
- realized and unrealized PnL
- exposure:
  - region
  - sector
  - theme
  - bucket

Functions:
- compute weights
- compute drift
- generate rebalance trades

---

### 5. Execution Engine

Handles order lifecycle.

Modes:
- paper
- dry-run
- live (future)

Responsibilities:
- translate instructions into orders
- simulate fills
- track order status
- update holdings and cash

---

### 6. Database Layer

Stores:

- holdings
- trades
- orders
- target allocations
- thesis entries
- cash ledger

---

### 7. Analytics Layer

Computes:

- portfolio return
- benchmark comparison
- drawdown
- contribution by:
  - asset
  - bucket
  - theme

---

### 8. Dashboard Layer

Displays:

- portfolio value
- allocation breakdown
- exposures
- PnL
- trade history
- thesis log

---

### 9. Content Layer (Optional)

Generates:

- weekly summaries
- portfolio reviews
- thesis updates

---

## Data Flow Example

1. User sends: /set_target FXI 12  
2. Parser → structured instruction  
3. Validator → check constraints  
4. Portfolio Engine → compute trades  
5. Execution → simulate trade  
6. Database → store updates  
7. Analytics → update metrics  
8. Dashboard → reflect changes  

---

## Design Principles

- deterministic logic
- modular architecture
- separation of concerns
- full auditability
- easy extensibility

---

## Future Extensions

- IBKR live integration
- factor analysis
- advanced risk metrics
- multi-account support
- automated reporting