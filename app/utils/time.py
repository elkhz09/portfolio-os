"""Time utilities — all display times are Singapore Time (SGT, UTC+8)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")


def now_sgt() -> datetime:
    """Return current time in SGT."""
    return datetime.now(tz=SGT)


def to_sgt(dt: datetime) -> datetime:
    """Convert a naive UTC datetime (as stored in the DB) to SGT."""
    return dt.replace(tzinfo=timezone.utc).astimezone(SGT)


def fmt_sgt(dt: datetime, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Format a naive UTC datetime as an SGT string."""
    return to_sgt(dt).strftime(fmt)
