"""Small scheduler-friendly entry point for official universe refreshes."""

from __future__ import annotations

import argparse
import json
from typing import Any, Callable, Mapping, Optional, Sequence

from .ch_universe import refresh_ch_universe
from .jp_universe import refresh_jp_universe
from ..us_universe import refresh_us_universe

Refresher = Callable[[], Mapping[str, Any]]


class DailyRefreshError(RuntimeError):
    """Raised after all requested markets run and at least one failed."""

    def __init__(
        self,
        failures: Mapping[str, str],
        results: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self.failures = dict(failures)
        self.results = dict(results)
        summary = "; ".join(f"{market}: {reason}" for market, reason in failures.items())
        super().__init__(f"Universe refresh failed for {summary}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="investment-monitor-refresh-universes",
        description="Refresh the official CH, JP and/or US universe caches once.",
    )
    parser.add_argument(
        "--market",
        action="append",
        choices=("ch", "jp", "us"),
        help="Market to refresh; repeat as needed. Defaults to ch, jp and us.",
    )
    return parser


def run_daily_refresh(
    markets: Sequence[str],
    *,
    refreshers: Optional[Mapping[str, Refresher]] = None,
) -> Mapping[str, Mapping[str, Any]]:
    """Run requested refreshers; any failed market makes the command fail."""
    available: Mapping[str, Refresher] = refreshers or {
        "ch": refresh_ch_universe,
        "jp": refresh_jp_universe,
        "us": refresh_us_universe,
    }
    unsupported = [market for market in markets if market not in available]
    if unsupported:
        raise ValueError(f"Unsupported universe market {unsupported[0]!r}")
    results = {}
    failures = {}
    for market in markets:
        try:
            payload = available[market]()
        except Exception as error:
            failures[market] = str(error) or type(error).__name__
            continue
        results[market] = {
            "updated_at": payload.get("updated_at"),
            "source_effective_date": payload.get("source_effective_date"),
            "counts": payload.get("counts", {}),
            "counts_by_type": payload.get("counts_by_type", {}),
            "coverage": payload.get("coverage"),
        }
    if failures:
        raise DailyRefreshError(failures, results)
    return results


def main(arguments: Optional[Sequence[str]] = None) -> None:
    parsed = build_parser().parse_args(arguments)
    markets = tuple(dict.fromkeys(parsed.market or ("ch", "jp", "us")))
    print(json.dumps(run_daily_refresh(markets), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["DailyRefreshError", "build_parser", "main", "run_daily_refresh"]
