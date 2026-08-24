"""Command-line workflow: configure, collect, persist, and report."""

from __future__ import annotations

import argparse
from datetime import date
import getpass
import logging
import os
from pathlib import Path
import sys
from typing import Optional, Sequence

from .application import run_workflow
from .config import load_settings


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
    argument_list = list(sys.argv[1:] if arguments is None else arguments)
    if argument_list[:1] == ["attach-legacy-login"]:
        attach_legacy_login_command(argument_list[1:])
        return
    parsed = build_parser().parse_args(argument_list)
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


def attach_legacy_login_command(arguments: Sequence[str]) -> None:
    """Opt-in primitive: make the legacy local data reachable from a login.

    Writes ``username`` / ``password_hash`` / ``role=admin`` onto the same
    ``legacy-local`` user row. Never part of the default collect or web
    startup paths; refused when the username already belongs to any user or
    the legacy row is already attached.
    """
    parser = argparse.ArgumentParser(
        prog="investment-monitor attach-legacy-login",
        description=(
            "Attach a username/password admin login to the legacy local "
            "data so the historical holdings become visible after logging in."
        ),
    )
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--settings", type=Path, default=Path("config/settings.yaml")
    )
    parser.add_argument(
        "--password-env",
        default="IM_ATTACH_LEGACY_PASSWORD",
        help="Environment variable holding the new password "
        "(falls back to an interactive prompt).",
    )
    parsed = parser.parse_args(arguments)

    from .auth import AccountError, SessionGate
    from .web_repository import WebRepository

    settings = load_settings(parsed.settings)
    # Ensure every migration (including the session-login schema) exists
    # before writing login fields onto the legacy row.
    WebRepository(settings.database_path)
    gate = SessionGate(settings.database_path)
    password = os.environ.get(parsed.password_env, "")
    if not password:
        password = getpass.getpass("New password for the legacy login: ")
    try:
        account = gate.attach_legacy_login(parsed.username, password)
    except AccountError as error:
        raise SystemExit(f"attach-legacy-login refused: {error}") from error
    print(
        "attached legacy data to admin login "
        f"'{account['username']}' (user id {account['id']})"
    )


if __name__ == "__main__":
    main()
