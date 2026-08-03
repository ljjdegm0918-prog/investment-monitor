"""Run configured sources for the configured ticker universe."""

import argparse
from datetime import date
import logging
from pathlib import Path

from investment_monitor import run_configured_collection


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    parser.add_argument(
        "--universe",
        type=Path,
        default=Path("config/universe.csv"),
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path("config/settings.yaml"),
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    arguments = parse_arguments()
    result = run_configured_collection(
        universe_path=arguments.universe,
        settings_path=arguments.settings,
        start_date=arguments.start_date,
        end_date=arguments.end_date,
    )
    print(
        f"collected={len(result.items)} "
        f"inserted={result.save_result.inserted} "
        f"updated={result.save_result.updated} "
        f"failures={len(result.failures)} "
        f"stored_total={result.stored_count} "
        f"database={result.database_path}"
    )


if __name__ == "__main__":
    main()
