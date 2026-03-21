"""CLI entrypoint for Portfolio OS.

Usage:
    python main.py bot         # Start the Telegram bot
    python main.py initdb      # Initialise / migrate the database
    python main.py status      # Print portfolio status to stdout
"""

import sys

from loguru import logger


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    command = sys.argv[1].lower()

    match command:
        case "bot":
            from app.interface.bot import run_bot
            run_bot()

        case "initdb":
            from app.db.init_db import init_db
            init_db()

        case "status":
            from app.db.session import SessionLocal
            from app.reports.generator import ReportGenerator
            with SessionLocal() as db:
                reporter = ReportGenerator(db)
                print(reporter.portfolio_summary())
                print()
                print(reporter.pnl_report())

        case _:
            logger.error("Unknown command: {!r}", command)
            print(__doc__)
            sys.exit(1)


if __name__ == "__main__":
    main()
