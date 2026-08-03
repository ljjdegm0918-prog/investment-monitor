"""Load the ticker universe and collection settings."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Dict, List, Tuple

ALLOWED_LIST_TYPES = frozenset({"holdings", "planned", "watchlist"})
ENVIRONMENT_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ConfigurationError(ValueError):
    """Raised when a project configuration file is invalid."""


@dataclass(frozen=True)
class UniverseEntry:
    ticker: str
    list_type: str


@dataclass(frozen=True)
class CollectionSettings:
    enabled_sources: Tuple[str, ...]
    database_path: Path


def load_environment_file(path: Path) -> None:
    """Load a small KEY=value file without overwriting real environment values."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    except OSError as error:
        raise ConfigurationError(f"Could not read environment file: {path}") from error

    for line_number, original_line in enumerate(lines, start=1):
        stripped = original_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped.removeprefix("export ").strip()
        if "=" not in stripped:
            raise ConfigurationError(
                f"Environment file line {line_number} must use KEY=value."
            )
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not ENVIRONMENT_KEY.fullmatch(key):
            raise ConfigurationError(
                f"Environment file line {line_number} has an invalid key."
            )
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def load_universe(path: Path) -> Tuple[UniverseEntry, ...]:
    """Read and validate 1–10 unique ticker rows from CSV."""
    try:
        with path.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            if reader.fieldnames is None:
                raise ConfigurationError("Universe CSV is missing a header row.")
            required_columns = {"ticker", "list_type"}
            if not required_columns.issubset(set(reader.fieldnames)):
                raise ConfigurationError(
                    "Universe CSV must contain ticker and list_type columns."
                )
            entries = [
                _parse_universe_row(row, row_number)
                for row_number, row in enumerate(reader, start=2)
            ]
    except OSError as error:
        raise ConfigurationError(
            f"Could not read universe CSV: {path}"
        ) from error

    if not 1 <= len(entries) <= 10:
        raise ConfigurationError(
            "Universe CSV must contain between 1 and 10 ticker rows."
        )
    tickers = [entry.ticker for entry in entries]
    if len(set(tickers)) != len(tickers):
        raise ConfigurationError("Universe CSV tickers must be unique.")
    return tuple(entries)


def load_settings(path: Path) -> CollectionSettings:
    """Load the small supported subset of settings.yaml."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ConfigurationError(
            f"Could not read settings YAML: {path}"
        ) from error

    enabled_sources: List[str] = []
    database_path_text = ""
    current_key = ""
    for line_number, original_line in enumerate(lines, start=1):
        content = original_line.split("#", 1)[0].rstrip()
        if not content.strip():
            continue
        stripped = content.strip()
        if not content.startswith((" ", "\t")) and stripped.endswith(":"):
            current_key = stripped[:-1].strip()
            if current_key != "enabled_sources":
                raise ConfigurationError(
                    f"Unsupported settings key on line {line_number}: "
                    f"{current_key}"
                )
            continue
        if stripped.startswith("-"):
            if current_key != "enabled_sources":
                raise ConfigurationError(
                    f"Unexpected YAML list item on line {line_number}."
                )
            source = _unquote(stripped[1:].strip())
            if not source:
                raise ConfigurationError(
                    f"Empty enabled source on line {line_number}."
                )
            enabled_sources.append(source)
            continue
        if ":" in stripped and not content.startswith((" ", "\t")):
            key, value = stripped.split(":", 1)
            key = key.strip()
            if key != "database_path":
                raise ConfigurationError(
                    f"Unsupported settings key on line {line_number}: {key}"
                )
            database_path_text = _unquote(value.strip())
            current_key = ""
            continue
        raise ConfigurationError(
            f"Unsupported YAML structure on line {line_number}."
        )

    if not enabled_sources:
        raise ConfigurationError(
            "settings.yaml must enable at least one source."
        )
    if len(set(enabled_sources)) != len(enabled_sources):
        raise ConfigurationError("Enabled source names must be unique.")
    if not database_path_text:
        raise ConfigurationError("settings.yaml must define database_path.")

    database_path = Path(database_path_text)
    if not database_path.is_absolute():
        database_path = path.parent / database_path
    return CollectionSettings(
        enabled_sources=tuple(enabled_sources),
        database_path=database_path,
    )


def _parse_universe_row(
    row: Dict[str, str],
    row_number: int,
) -> UniverseEntry:
    ticker = (row.get("ticker") or "").strip().upper()
    list_type = (row.get("list_type") or "").strip().lower()
    if not ticker:
        raise ConfigurationError(
            f"Universe CSV row {row_number} has an empty ticker."
        )
    if not ticker.replace(".", "").replace("-", "").isalnum():
        raise ConfigurationError(
            f"Universe CSV row {row_number} has an invalid ticker: {ticker}"
        )
    if list_type not in ALLOWED_LIST_TYPES:
        allowed = ", ".join(sorted(ALLOWED_LIST_TYPES))
        raise ConfigurationError(
            f"Universe CSV row {row_number} list_type must be one of: {allowed}."
        )
    return UniverseEntry(ticker=ticker, list_type=list_type)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
