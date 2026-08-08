"""Command-line interface for the official EDINET connector."""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any, Optional, Sequence

from ...config import load_environment_file
from .connector import EDINETCompanyInput, EDINETConnector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edinet", description="Official EDINET API v2 tools")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    feed = subparsers.add_parser("login-feed", help="Return recent watchlist disclosures")
    feed.add_argument("--watchlist", default="")
    feed.add_argument("--watchlist-file", type=Path)
    feed.add_argument("--since", default="24h")
    feed.add_argument("--download", action="store_true")
    feed.add_argument("--download-types", default="1,2")

    sync = subparsers.add_parser("sync", help="Synchronize daily document metadata")
    sync.add_argument("--from", dest="start_date", type=date.fromisoformat)
    sync.add_argument("--to", dest="end_date", type=date.fromisoformat)
    sync.add_argument("--incremental", action="store_true")

    subparsers.add_parser("refresh-codes", help="Refresh official EDINET code list")
    return parser


def main(arguments: Optional[Sequence[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parsed = build_parser().parse_args(arguments)
    load_environment_file(parsed.project_root / ".env")
    connector = EDINETConnector.from_environment()
    if parsed.command == "login-feed":
        companies = _watchlist(parsed.watchlist, parsed.watchlist_file)
        now = datetime.now(timezone.utc)
        result = connector.get_watchlist_disclosures_since(
            companies=companies,
            since=now - _duration(parsed.since),
            now=now,
            include_downloads=parsed.download,
            download_types=tuple(int(value) for value in parsed.download_types.split(",")),
        )
        print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2, sort_keys=True))
    elif parsed.command == "sync":
        if parsed.incremental:
            result = connector.sync_incremental()
        else:
            if parsed.start_date is None or parsed.end_date is None:
                raise SystemExit("sync requires --from and --to, or --incremental")
            result = connector.sync_range(parsed.start_date, parsed.end_date)
        print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps({"code_count": connector.refresh_code_list()}, indent=2))


def _watchlist(raw: str, path: Optional[Path]) -> Sequence[Any]:
    if path:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("watchlist file must contain a JSON array")
        return payload
    values = tuple(value.strip() for value in raw.split(",") if value.strip())
    if not values:
        raise ValueError("watchlist must not be empty")
    return values


def _duration(value: str) -> timedelta:
    match = re.fullmatch(r"([1-9][0-9]*)([hd])", value.strip().lower())
    if not match:
        raise ValueError("since must look like 24h or 2d")
    amount = int(match.group(1))
    return timedelta(hours=amount) if match.group(2) == "h" else timedelta(days=amount)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date, Path)):
        return value.isoformat() if not isinstance(value, Path) else str(value)
    return value


if __name__ == "__main__":
    main()