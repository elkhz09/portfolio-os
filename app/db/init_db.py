"""Create all database tables. Run once on first setup."""

from app.db.models import Base
from app.db.session import engine
from loguru import logger


def init_db() -> None:
    """Create tables if they do not exist."""
    logger.info("Initialising database at: {}", engine.url)
    Base.metadata.create_all(bind=engine)
    logger.info("Database ready.")


if __name__ == "__main__":
    init_db()
