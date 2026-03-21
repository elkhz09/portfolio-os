"""Database seed script.

Creates an empty portfolio with an initial cash deposit.
Safe to run multiple times — idempotent when the ledger already has entries.

Usage
-----
    python -m app.db.seed                        # default $100,000
    python -m app.db.seed --cash 250000          # custom starting cash
"""

from __future__ import annotations

import argparse

from loguru import logger
from sqlalchemy.orm import Session

from app.db.ledger import append_cash_entry, get_cash_balance
from app.db.models import AuditLog, CashEntryType, CashLedger
from app.db.session import SessionLocal


def seed_empty_portfolio(
    db: Session,
    starting_cash: float = 100_000.0,
    note: str = "Initial deposit — portfolio seeded",
) -> CashLedger | None:
    """Create an empty portfolio with *starting_cash* in the cash ledger.

    Idempotent: if the ledger already contains entries this function logs a
    warning and returns ``None`` without modifying any data.

    Args:
        db: Active database session.  The caller is responsible for committing.
        starting_cash: Opening cash balance in base currency units.
        note: Description attached to the opening ledger entry.

    Returns:
        The new ``CashLedger`` row, or ``None`` if already seeded.
    """
    if starting_cash <= 0:
        raise ValueError(f"starting_cash must be positive, got {starting_cash}")

    existing = db.query(CashLedger).first()
    if existing is not None:
        logger.warning(
            "Portfolio already seeded (cash balance = {:,.2f}). Skipping.",
            get_cash_balance(db),
        )
        return None

    entry = append_cash_entry(
        db,
        entry_type=CashEntryType.DEPOSIT,
        amount=starting_cash,
        note=note,
    )
    db.add(
        AuditLog(
            event="PORTFOLIO_SEEDED",
            detail=f"starting_cash={starting_cash:.2f}",
        )
    )
    logger.info("Portfolio seeded with starting cash: {:,.2f}", starting_cash)
    return entry


def _main() -> None:
    parser = argparse.ArgumentParser(description="Seed an empty portfolio.")
    parser.add_argument(
        "--cash",
        type=float,
        default=100_000.0,
        help="Starting cash balance (default: 100000)",
    )
    parser.add_argument(
        "--note",
        type=str,
        default="Initial deposit — portfolio seeded",
        help="Description for the opening ledger entry",
    )
    args = parser.parse_args()

    from app.db.init_db import init_db
    init_db()

    with SessionLocal() as db:
        result = seed_empty_portfolio(db, starting_cash=args.cash, note=args.note)
        if result is not None:
            db.commit()
            print(f"Done. Opening balance: ${args.cash:,.2f}")
        else:
            print("Already seeded — nothing changed.")


if __name__ == "__main__":
    _main()
