"""Command-line workflow: configure, collect, persist, and report."""

from __future__ import annotations

import argparse
from datetime import date
import logging
from pathlib import Path
from typing import Optional, Sequence

from .application import run_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="investment-monitor",
        description=(
            "Collect enabled investment sources, save them to SQLite, "
            "and generate a static HTML report."
        ),
    )
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
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/announcements.html"),
    )
    return parser


def main(arguments: Optional[Sequence[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parsed = build_parser().parse_args(arguments)
    result = run_workflow(
        universe_path=parsed.universe,
        settings_path=parsed.settings,
        start_date=parsed.start_date,
        end_date=parsed.end_date,
        output_path=parsed.output,
    )
    print(
        f"collected={result.collected_count} "
        f"inserted={result.save_result.inserted} "
        f"updated={result.save_result.updated} "
        f"failures={result.failure_count} "
        f"stored_total={result.stored_count} "
        f"report_records={result.report.record_count} "
        f"report={result.report.output_path}"
    )


if __name__ == "__main__":
    main()
