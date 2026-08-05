"""Load the ticker universe and collection settings."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

from .models import ALLOWED_MARKETS, MARKET_US

ALLOWED_LIST_TYPES = frozenset({"holdings", "planned", "watchlist"})
ENVIRONMENT_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SUPPORTED_SETTINGS_KEYS = frozenset({"sources", "enabled_sources", "database_path"})
# Fallback metadata for the legacy enabled_sources-only settings format.
DEFAULT_SOURCE_META = {
    "sec": ("SEC EDGAR", "filings"),
    "dart": ("OpenDART", "filings"),
    "kind": ("KIND (KRX)", "filings"),
    "companies_house": ("Companies House", "filings"),
    "investegate": ("Investegate", "filings"),
    "naver_news": ("Naver Finance", "news"),
    "hankyung": ("Hankyung", "news"),
    "thebell": ("TheBell", "news"),
    "yahoo_uk": ("Yahoo Finance UK", "news"),
    "news": ("News", "news"),
    "community": ("Community", "community"),
    "research": ("Research", "research"),
    "mock": ("Mock", "mock"),
    "mock_community": ("Mock Community", "community"),
}


class ConfigurationError(ValueError):
    """Raised when a project configuration file is invalid."""


@dataclass(frozen=True)
class UniverseEntry:
    ticker: str
    list_type: str
    market: str = MARKET_US


@dataclass(frozen=True)
class SourceConfig:
    """One logical source declared in application configuration."""

    name: str
    label: str = ""
    source_type: str = "other"
    enabled: bool = False


@dataclass(frozen=True)
class CollectionSettings:
    database_path: Path
    sources: Tuple[SourceConfig, ...] = ()

    @property
    def enabled_sources(self) -> Tuple[str, ...]:
        """Return the names of enabled logical sources."""
        return tuple(source.name for source in self.sources if source.enabled)


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
    """Read and validate 1-10 unique (ticker, market) rows from CSV."""
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
    identities = [(entry.ticker, entry.market) for entry in entries]
    if len(set(identities)) != len(identities):
        raise ConfigurationError(
            "Universe CSV (ticker, market) pairs must be unique."
        )
    return tuple(entries)


def load_settings(path: Path) -> CollectionSettings:
    """Load the small supported subset of settings.yaml."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ConfigurationError(
            f"Could not read settings YAML: {path}"
        ) from error

    enabled_source_names: List[str] = []
    sources: List[SourceConfig] = []
    database_path_text = ""
    current_key = ""
    current_source: Optional[Dict[str, str]] = None

    def finish_source(line_number: int) -> None:
        nonlocal current_source
        if current_source is None:
            return
        source = _parse_source(current_source, line_number)
        if any(existing.name == source.name for existing in sources):
            raise ConfigurationError(
                f"Source names must be unique; duplicate: {source.name}"
            )
        sources.append(source)
        current_source = None

    for line_number, original_line in enumerate(lines, start=1):
        content = original_line.split("#", 1)[0].rstrip()
        if not content.strip():
            continue
        stripped = content.strip()
        indented = content.startswith((" ", "\t"))

        if not indented:
            finish_source(line_number)
            current_source = None

        if not indented and stripped.endswith(":"):
            current_key = stripped[:-1].strip()
            if current_key not in SUPPORTED_SETTINGS_KEYS:
                raise ConfigurationError(
                    f"Unsupported settings key on line {line_number}: "
                    f"{current_key}"
                )
            continue

        if indented and current_key == "sources" and stripped.startswith("-"):
            finish_source(line_number)
            current_source = {}
            remainder = stripped[1:].strip()
            if remainder:
                if ":" not in remainder:
                    raise ConfigurationError(
                        f"Source entries must use key: value pairs on line "
                        f"{line_number}."
                    )
                key, value = remainder.split(":", 1)
                current_source[key.strip()] = _unquote(value.strip())
            continue

        if indented and current_key == "sources":
            if current_source is None:
                raise ConfigurationError(
                    f"Expected a '- name: ...' list item before line "
                    f"{line_number}."
                )
            if ":" not in stripped:
                raise ConfigurationError(
                    f"Source entries must use key: value pairs on line "
                    f"{line_number}."
                )
            key, value = stripped.split(":", 1)
            current_source[key.strip()] = _unquote(value.strip())
            continue

        if indented and current_key == "enabled_sources":
            if not stripped.startswith("-"):
                raise ConfigurationError(
                    f"Unexpected YAML structure on line {line_number}."
                )
            source_name = _unquote(stripped[1:].strip())
            if not source_name:
                raise ConfigurationError(
                    f"Empty enabled source on line {line_number}."
                )
            enabled_source_names.append(source_name)
            continue

        if not indented and ":" in stripped:
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

    finish_source(len(lines) + 1)

    if sources and enabled_source_names:
        raise ConfigurationError(
            "settings.yaml must use either 'sources' or 'enabled_sources', "
            "not both."
        )
    if not sources and enabled_source_names:
        sources = [_legacy_source(name) for name in enabled_source_names]

    if not any(source.enabled for source in sources):
        raise ConfigurationError(
            "settings.yaml must enable at least one source."
        )
    if not database_path_text:
        raise ConfigurationError("settings.yaml must define database_path.")

    database_path = Path(database_path_text)
    if not database_path.is_absolute():
        database_path = path.parent / database_path
    return CollectionSettings(
        database_path=database_path,
        sources=tuple(sources),
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
    market = (row.get("market") or "").strip().lower() or MARKET_US
    if market not in ALLOWED_MARKETS:
        allowed = ", ".join(sorted(ALLOWED_MARKETS))
        raise ConfigurationError(
            f"Universe CSV row {row_number} market must be one of: {allowed}."
        )
    return UniverseEntry(ticker=ticker, list_type=list_type, market=market)


def _parse_source(
    raw: Dict[str, str],
    line_number: int,
) -> SourceConfig:
    name = (raw.get("name") or "").strip()
    if not name:
        raise ConfigurationError(
            f"Source entry near line {line_number} must define a name."
        )
    label = (raw.get("label") or "").strip() or name
    source_type = (raw.get("source_type") or "").strip() or "other"
    enabled = _parse_bool(raw.get("enabled"), line_number, default=False)
    return SourceConfig(
        name=name,
        label=label,
        source_type=source_type,
        enabled=enabled,
    )


def _legacy_source(name: str) -> SourceConfig:
    label, source_type = DEFAULT_SOURCE_META.get(
        name,
        (name, "other"),
    )
    return SourceConfig(
        name=name,
        label=label,
        source_type=source_type,
        enabled=True,
    )


def _parse_bool(
    value: Optional[str],
    line_number: int,
    *,
    default: bool,
) -> bool:
    if value is None or not str(value).strip():
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "yes", "on", "1"}:
        return True
    if normalized in {"false", "no", "off", "0"}:
        return False
    raise ConfigurationError(
        f"enabled must be true or false on line {line_number}."
    )


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
