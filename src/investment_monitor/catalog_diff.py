# -*- coding: utf-8 -*-
"""Quarterly static coverage-benchmark diff helper.

Usage (from the repo root):

    PYTHONPATH=src python -m investment_monitor.catalog_diff
    PYTHONPATH=src python -m investment_monitor.catalog_diff --write-snapshot
    PYTHONPATH=src python -m investment_monitor.catalog_diff --json

Reads the current seed ``universe/ibkr_exchange_catalog.json`` and a
previous snapshot (default ``docs/ibkr_catalog_snapshot.json``), then
prints the frozen 28/87 summary plus added/removed/changed country and
venue rows. Updating the snapshot is a manual, offline benchmark task;
the helper never logs in to or calls a broker service.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

DEFAULT_SNAPSHOT = Path("docs/ibkr_catalog_snapshot.json")


def _load(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _row_key_country(row: Mapping[str, Any]) -> str:
    return str(row.get("country_code") or "")


def _row_key_venue(row: Mapping[str, Any]) -> str:
    return f"{row.get('country_code')}:{row.get('venue_id')}"


def _diff(
    old_rows: Sequence[Mapping[str, Any]],
    new_rows: Sequence[Mapping[str, Any]],
    key_fn,
) -> Dict[str, List[Dict[str, Any]]]:
    old_by_key = {key_fn(row): row for row in old_rows}
    new_by_key = {key_fn(row): row for row in new_rows}
    added = [
        dict(row) for key, row in new_by_key.items() if key not in old_by_key
    ]
    removed = [
        dict(row) for key, row in old_by_key.items() if key not in new_by_key
    ]
    changed = []
    for key in sorted(set(old_by_key) & set(new_by_key)):
        if old_by_key[key] != new_by_key[key]:
            changed.append(
                {
                    "key": key,
                    "old": old_by_key[key],
                    "new": new_by_key[key],
                }
            )
    return {"added": added, "removed": removed, "changed": changed}


def compare_catalogs(
    old: Mapping[str, Any],
    new: Mapping[str, Any],
) -> Dict[str, Any]:
    """Compare two catalog payloads and return a JSON-safe diff report."""
    old_countries = list(old.get("countries") or [])
    new_countries = list(new.get("countries") or [])
    country_diff = _diff(old_countries, new_countries, _row_key_country)
    venue_diff = _diff(old.get("venues") or [], new.get("venues") or [], _row_key_venue)

    def region_counts(payload: Mapping[str, Any]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for venue in payload.get("venues") or []:
            region = str(venue.get("region") or "Other")
            counts[region] = counts.get(region, 0) + 1
        return counts

    return {
        "current": {
            "countries": len(new_countries),
            "venues": len(new.get("venues") or []),
            "regions": region_counts(new),
        },
        "previous": {
            "countries": len(old_countries),
            "venues": len(old.get("venues") or []),
            "regions": region_counts(old),
        },
        "countries": country_diff,
        "venues": venue_diff,
    }


def _current_catalog_path() -> Path:
    return Path(__file__).parent / "universe" / "ibkr_exchange_catalog.json"


def run(
    argv: Optional[Sequence[str]] = None,
) -> Tuple[Dict[str, Any], int]:
    parser = argparse.ArgumentParser(
        description="Quarterly coverage benchmark diff (28 countries / 87 venues)."
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=DEFAULT_SNAPSHOT,
        help="previous snapshot JSON (default: docs/ibkr_catalog_snapshot.json)",
    )
    parser.add_argument(
        "--write-snapshot",
        action="store_true",
        help="overwrite the snapshot with the current catalog",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the diff report as JSON",
    )
    args = parser.parse_args(argv)

    current_path = _current_catalog_path()
    current = _load(current_path)

    if args.write_snapshot:
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        with args.snapshot.open("w", encoding="utf-8") as handle:
            json.dump(current, handle, ensure_ascii=False, indent=1)
        print(f"wrote snapshot: {args.snapshot}")
        return {"written_snapshot": str(args.snapshot)}, 0

    if not args.snapshot.exists():
        print(
            f"snapshot missing: {args.snapshot}\n"
            "run with --write-snapshot first (quarterly baseline)",
            file=sys.stderr,
        )
        return {}, 2

    previous = _load(args.snapshot)
    report = compare_catalogs(previous, current)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        cur = report["current"]
        print(
            f"current catalog: countries={cur['countries']} "
            f"venues={cur['venues']} regions={cur['regions']}"
        )
        for kind in ("countries", "venues"):
            diff = report[kind]
            print(
                f"{kind}: added={len(diff['added'])} "
                f"removed={len(diff['removed'])} changed={len(diff['changed'])}"
            )
        for kind in ("countries", "venues"):
            for row in report[kind]["removed"]:
                key = _row_key_country(row) if kind == "countries" else _row_key_venue(row)
                print(f"  removed {kind[:-1]}: {key}")
            for row in report[kind]["added"]:
                key = _row_key_country(row) if kind == "countries" else _row_key_venue(row)
                print(f"  added {kind[:-1]}: {key}")
    return report, 0


if __name__ == "__main__":
    _report, code = run()
    raise SystemExit(code)
