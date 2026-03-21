"""Cash ledger helpers.

All cash movements go through ``append_cash_entry`` so that the running
balance in ``CashLedger.balance_after`` stays consistent.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import CashEntryType, CashLedger


def get_cash_balance(db: Session) -> float:
    """Return the current cash balance.

    Reads the ``balance_after`` of the most recent ledger row.
    Returns 0.0 if the ledger is empty.

    Args:
        db: Active database session.
    """
    last = (
        db.query(CashLedger)
        .order_by(CashLedger.id.desc())
        .first()
    )
    return last.balance_after if last else 0.0


def append_cash_entry(
    db: Session,
    entry_type: CashEntryType,
    amount: float,
    *,
    order_id: int | None = None,
    note: str | None = None,
    occurred_at: datetime | None = None,
) -> CashLedger:
    """Append a new cash ledger entry and return it.

    Computes ``balance_after`` automatically from the last ledger row so
    callers do not need to track the running balance themselves.

    Args:
        db: Active database session.
        entry_type: Nature of the cash movement.
        amount: Positive for inflows (deposits, sell proceeds), negative for
            outflows (withdrawals, buy settlements, fees).
        order_id: FK to the order that triggered this movement, if any.
        note: Optional human-readable description.
        occurred_at: Timestamp to record; defaults to now.

    Returns:
        The newly created and flushed ``CashLedger`` row.
    """
    current_balance = get_cash_balance(db)
    entry = CashLedger(
        entry_type=entry_type,
        amount=amount,
        balance_after=current_balance + amount,
        order_id=order_id,
        note=note,
        occurred_at=occurred_at or datetime.utcnow(),
    )
    db.add(entry)
    db.flush()  # assign PK without committing the outer transaction
    return entry
