"""Testable local HTTP application for the investment monitor web MVP."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
import os
from pathlib import Path
import threading
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from .application import ConfiguredCollectionResult, run_ticker_collection
from .config import (
    SourceConfig,
    load_environment_file,
    load_settings,
    load_universe,
)
from .connectors.base import ConnectorUnavailableError
from .daily import resolve_timezone
from .hk_universe import hk_universe_name_map
from .kr_universe import kr_universe_name_map
from .models import MARKET_HK, MARKET_KR, MARKET_UK, MARKET_US
from .pipeline import CollectionEvent
from .registry import SourceRegistry, create_default_registry
from .sources.companies_house import CompaniesHouseCompanyResolver
from .sources.companies_house.company_cache import number_cache_path
from .sources.dart import DARTCompanyResolver
from .sources.hkexnews import HKEXNewsCompanyResolver
from .sources.sec.client import SECConfigurationError
from .sources.sec.company_resolver import SECCompanyResolver
from .sqlite_repository import SQLiteInformationRepository
from .uk_universe import uk_universe_name_map
from .web_repository import EXTRA_ENV_PREFIX, FeedFilters, WebRepository

LOGGER = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")

TOPBAR_STATUS_LEVELS = {
    "not_connected": 1,
    "connected": 2,
    "stale": 3,
    "unavailable": 4,
    "temporarily_unavailable": 4,
    "failed": 5,
}
TOPBAR_STATUS_WORDS = {
    "connected": "up to date",
    "stale": "stale",
    "unavailable": "unavailable",
    "not_connected": "not connected",
    "temporarily_unavailable": "temporarily unavailable",
    "failed": "failed",
}
CollectionRunner = Callable[..., ConfiguredCollectionResult]


def build_provider_catalog(
    registry: SourceRegistry,
    sources: Sequence[SourceConfig],
) -> Sequence[Mapping[str, Any]]:
    """Describe implemented sources and their declared credential fields."""
    providers = []
    for source in sources:
        if source.name.startswith("mock"):
            continue
        factory = registry.factory_for(source.name)
        providers.append(
            {
                "name": source.name,
                "label": source.label,
                "source_type": source.source_type,
                "enabled": source.enabled,
                "implemented": factory is not None,
                "fields": [
                    {
                        "env": field.env,
                        "label": field.label,
                        "kind": field.kind,
                        "help": field.help,
                    }
                    for field in registry.secret_fields_for(source.name)
                ],
            }
        )
    return tuple(providers)


@dataclass(frozen=True)
class WebResponse:
    status: int
    body: bytes
    content_type: str = "application/json; charset=utf-8"


class WebApplication:
    """Pure request dispatcher used by both HTTP server and tests."""

    def __init__(
        self,
        project_root: Path,
        *,
        collection_runner: CollectionRunner = run_ticker_collection,
    ) -> None:
        self.project_root = project_root
        load_environment_file(project_root / ".env")
        self.settings_path = project_root / "config" / "settings.yaml"
        settings = load_settings(self.settings_path)
        configured_sources = tuple(settings.enabled_sources)
        allowed_sources = tuple(
            source for source in configured_sources if not source.startswith("mock")
        )
        self.enabled_sources = allowed_sources
        registry = create_default_registry()
        self._registry = registry
        self.implemented_sources = tuple(registry.registered_names)
        self.source_catalog = tuple(
            source
            for source in settings.sources
            if not source.name.startswith("mock")
        )
        self.provider_catalog = build_provider_catalog(
            registry,
            self.source_catalog,
        )
        self.writable_env_keys = tuple(
            sorted(
                {
                    field["env"]
                    for provider in self.provider_catalog
                    for field in provider["fields"]
                }
            )
        )
        # Base filing tables must exist before the web migration and universe import.
        SQLiteInformationRepository(settings.database_path)
        self.repository = WebRepository(
            settings.database_path,
            allowed_sources=allowed_sources,
            known_sources=self.source_catalog,
            implemented_sources=self.implemented_sources,
            allowed_secret_keys=self.writable_env_keys,
        )
        # DB/UI-stored secrets take priority over .env for this process.
        self._load_credentials_to_environment()
        self.unavailable_sources = self._detect_unavailable_sources(
            registry,
            settings.sources,
        )
        self.repository.set_unavailable_sources(self.unavailable_sources)
        self.repository.import_universe(load_universe(project_root / "config" / "universe.csv"))
        cache_path = project_root / ".cache" / "investment_monitor" / "company_tickers.json"
        try:
            self.resolver = SECCompanyResolver.from_environment(cache_path)
        except SECConfigurationError:
            self.resolver = SECCompanyResolver(cache_path)
        dart_cache_path = (
            project_root
            / ".cache"
            / "investment_monitor"
            / "dart_corp_codes.json"
        )
        try:
            self.dart_resolver = DARTCompanyResolver.from_environment(
                dart_cache_path
            )
        except ConnectorUnavailableError:
            self.dart_resolver = DARTCompanyResolver.offline(dart_cache_path)
        companies_house_cache_path = number_cache_path()
        try:
            self.companies_house_resolver = (
                CompaniesHouseCompanyResolver.from_environment(
                    companies_house_cache_path
                )
            )
        except ConnectorUnavailableError:
            self.companies_house_resolver = (
                CompaniesHouseCompanyResolver.offline(
                    companies_house_cache_path
                )
            )
        try:
            self.companies_house_resolver.revalidate_legacy(self.repository)
        except Exception:
            LOGGER.exception(
                "Companies House legacy mapping revalidation failed"
            )
        self.hkexnews_resolver = HKEXNewsCompanyResolver()
        self.static_root = Path(__file__).parent / "web_static"
        self._collection_runner = collection_runner
        self._collection_lock = threading.Lock()

    def handle(
        self,
        method: str,
        target: str,
        body: bytes = b"",
    ) -> WebResponse:
        parsed = urlparse(target)
        query = parse_qs(parsed.query)
        try:
            if method == "GET" and parsed.path == "/favicon.ico":
                return WebResponse(204, b"", "image/x-icon")
            if method == "GET" and parsed.path.startswith("/static/"):
                return self._static(parsed.path)
            if method == "GET" and parsed.path in {
                "/", "/today", "/information", "/search", "/activity",
                "/sources", "/settings", "/lists/holdings",
                "/lists/planned", "/lists/watchlist",
            }:
                return self._html(parsed.path)
            if method == "GET" and parsed.path == "/api/bootstrap":
                return self._json(self._bootstrap(query))
            if method == "GET" and parsed.path == "/api/feed":
                return self._json(self._feed(query))
            if method == "GET" and parsed.path == "/api/companies":
                return self._json({"companies": self.repository.companies(_first(query, "list"))})
            if method == "GET" and parsed.path == "/api/activity":
                return self._json(self.repository.activity(
                    source=_first(query, "source"),
                    status=_first(query, "status"),
                    start_date=_query_date(query, "start_date"),
                    end_date=_query_date(query, "end_date"),
                ))
            if method == "GET" and parsed.path == "/api/sources":
                return self._json({"sources": self.repository.source_statuses()})
            if method == "POST" and parsed.path == "/api/companies/batch":
                payload = _decode_json(body)
                market = str(payload.get("market") or MARKET_US)
                resolver = self._resolver_for(market)
                name_fallback = None
                if market == MARKET_KR:
                    name_fallback = kr_universe_name_map()
                elif market == MARKET_UK:
                    name_fallback = uk_universe_name_map()
                elif market == MARKET_HK:
                    name_fallback = hk_universe_name_map()
                result = dict(self.repository.add_companies_batch(
                    str(payload.get("tickers", "")),
                    tuple(payload.get("lists") or ()),
                    resolver,
                    market=market,
                    name_fallback=name_fallback,
                ))
                added_tickers = tuple(
                    str(record["ticker"]) for record in result["added"]
                )
                if added_tickers:
                    result["collection"] = self.collect_tickers(
                        added_tickers,
                        lookback_days=_environment_int(
                            "INITIAL_BACKFILL_DAYS", 365, minimum=1, maximum=3650
                        ),
                        markets={ticker: market for ticker in added_tickers},
                    )
                return self._json(result, 201)
            if method == "POST" and parsed.path == "/api/companies/confirm-mapping":
                payload = _decode_json(body)
                ticker = str(payload.get("ticker") or "").strip()
                market = str(payload.get("market") or MARKET_UK)
                company_number = str(
                    payload.get("company_number") or ""
                ).strip() or None
                resolver = self._resolver_for(market)
                confirm = getattr(resolver, "confirm", None)
                identity = (
                    confirm(ticker, company_number=company_number)
                    if confirm is not None
                    else None
                )
                if identity is None:
                    return self._json(
                        {
                            "error": (
                                "Companies House verification failed; "
                                "mapping stays unverified."
                            )
                        },
                        409,
                    )
                self.repository.set_company_mapping(identity, market)
                return self._json(dict(identity), 200)
            if method == "POST" and parsed.path == "/api/memberships/remove":
                payload = _decode_json(body)
                removed = self.repository.remove_membership(
                    str(payload["ticker"]),
                    str(payload["list"]),
                    str(payload.get("market") or MARKET_US),
                )
                return self._json({"removed": removed})
            if method == "POST" and parsed.path == "/api/companies/remove-all":
                payload = _decode_json(body)
                removed_memberships = self.repository.remove_all_memberships(
                    str(payload["ticker"]),
                    str(payload.get("market") or MARKET_US),
                )
                return self._json({"removed_memberships": removed_memberships})
            if method == "POST" and parsed.path == "/api/read":
                payload = _decode_json(body)
                updated = self.repository.set_read(
                    tuple(payload.get("item_ids") or ()), _required_bool(payload, "is_read")
                )
                return self._json({"updated": updated})
            if method == "POST" and parsed.path == "/api/read/bulk":
                payload = _decode_json(body)
                filters = _filters_from_mapping(payload.get("filters") or {})
                updated = self.repository.bulk_set_read(filters, _required_bool(payload, "is_read"))
                return self._json({"updated": updated})
            if method == "GET" and parsed.path == "/api/settings":
                return self._json(self._settings_payload())
            if method == "POST" and parsed.path == "/api/settings":
                payload = _decode_json(body)
                key = str(payload["key"])
                value = str(payload.get("value") or "")
                self.repository.set_setting(key, value)
                is_credential = (
                    key in self.writable_env_keys
                    or key.startswith(EXTRA_ENV_PREFIX)
                )
                if is_credential:
                    env_name = (
                        key[len(EXTRA_ENV_PREFIX):]
                        if key.startswith(EXTRA_ENV_PREFIX)
                        else key
                    )
                    self._sync_environment_value(env_name, value)
                    self._refresh_unavailable_sources()
                    status = self.repository.setting_status([key])[key]
                    return self._json(
                        {
                            "updated": True,
                            "configured": status["configured"],
                            "hint": status["hint"],
                        }
                    )
                return self._json({"updated": True})
            return self._json({"error": "Not found"}, 404)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            return self._json({"error": str(error)}, 400)
        except Exception:
            LOGGER.exception("Web request failed: %s %s", method, target)
            return self._json(
                {"error": "The request could not be completed. Please retry."}, 500
            )

    def collect_tickers(
        self,
        tickers: Sequence[str],
        *,
        lookback_days: int,
        today: Optional[date] = None,
        markets: Optional[Mapping[str, str]] = None,
    ) -> Mapping[str, Any]:
        """Collect an explicit ticker set and return a JSON-safe summary."""
        normalized = tuple(dict.fromkeys(ticker.strip().upper() for ticker in tickers))
        if not normalized:
            return _empty_collection_summary(())
        market_map = {
            ticker: str((markets or {}).get(ticker) or MARKET_US)
            for ticker in normalized
        }
        end_date = today or datetime.now(EASTERN).date()
        start_date = end_date - timedelta(days=lookback_days)
        with self._collection_lock:
            try:
                result = self._collection_runner(
                    tickers=normalized,
                    settings_path=self.settings_path,
                    start_date=start_date,
                    end_date=end_date,
                    markets=market_map,
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                LOGGER.exception("Collection setup failed for %s", ", ".join(normalized))
                self._record_setup_failures(normalized, message)
                return {
                    "status": "failure",
                    "tickers": list(normalized),
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "records_fetched": 0,
                    "inserted": 0,
                    "updated": 0,
                    "failures": [
                        {"ticker": ticker, "message": message} for ticker in normalized
                    ],
                }
        failures = [
            {"ticker": failure.ticker, "message": failure.message}
            for failure in result.failures
        ]
        status = (
            "failure"
            if failures and len(failures) == len(normalized)
            else "partial"
            if failures
            else "success"
            if result.items
            else "empty"
        )
        return {
            "status": status,
            "tickers": list(normalized),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "records_fetched": len(result.items),
            "inserted": result.save_result.inserted,
            "updated": result.save_result.updated,
            "failures": failures,
        }

    def collect_active_companies(
        self,
        *,
        lookback_days: int,
        today: Optional[date] = None,
    ) -> Mapping[str, Any]:
        """Collect every company that still belongs to at least one list."""
        active_companies = self.repository.active_companies()
        if not active_companies:
            return _empty_collection_summary(())
        backfill_companies = set(
            self.repository.active_companies_without_any_source_items(
                self.enabled_sources
            )
        )
        backfill_by_market: Dict[str, List[str]] = {}
        incremental_by_market: Dict[str, List[str]] = {}
        for ticker, market in active_companies:
            destination = (
                backfill_by_market
                if (ticker, market) in backfill_companies
                else incremental_by_market
            )
            destination.setdefault(market, []).append(ticker)
        summaries = []
        for market, tickers in sorted(backfill_by_market.items()):
            summaries.append(self.collect_tickers(
                tuple(sorted(set(tickers))),
                lookback_days=_environment_int(
                    "INITIAL_BACKFILL_DAYS", 365, minimum=1, maximum=3650
                ),
                today=today,
                markets={ticker: market for ticker in set(tickers)},
            ))
        for market, tickers in sorted(incremental_by_market.items()):
            summaries.append(self.collect_tickers(
                tuple(sorted(set(tickers))),
                lookback_days=lookback_days,
                today=today,
                markets={ticker: market for ticker in set(tickers)},
            ))
        return _combine_collection_summaries(summaries)

    def _record_setup_failures(self, tickers: Sequence[str], message: str) -> None:
        occurred_at = datetime.now(timezone.utc)
        events = tuple(
            CollectionEvent(
                source=source,
                ticker=ticker,
                started_at=occurred_at,
                finished_at=occurred_at,
                status="failure",
                records_read=0,
                records_written=0,
                records_inserted=0,
                records_updated=0,
                duplicate_records=0,
                error_message=message,
            )
            for source in self.enabled_sources
            for ticker in tickers
        )
        if events:
            self.repository.record_collection_events(events)

    def _resolver_for(self, market: str) -> Any:
        """Pick the company resolver for a market (KR uses OpenDART)."""
        if market == MARKET_KR:
            return self.dart_resolver
        if market == MARKET_UK:
            # UK maps through Companies House; never let SEC map a UK ticker
            # to a same-named US company.
            return self.companies_house_resolver
        if market == MARKET_HK:
            # HK maps through the HKEXnews active stock list; never let SEC
            # map a Hong Kong code to a same-named US company.
            return self.hkexnews_resolver
        return self.resolver

    @staticmethod
    def _detect_unavailable_sources(
        registry: Any,
        catalog: Sequence[Any],
    ) -> Mapping[str, str]:
        """Find enabled catalog sources whose connector lacks configuration."""
        unavailable: Dict[str, str] = {}
        for source in catalog:
            if not source.enabled:
                continue
            reason = registry.configuration_error_for(source.name)
            if reason:
                unavailable[source.name] = str(reason)
        return unavailable

    def _load_credentials_to_environment(self) -> None:
        """Apply stored provider credentials and extra env vars to os.environ.

        Runs after load_environment_file(.env), so a value saved through the
        Settings page (database) intentionally wins over the .env default.
        """
        for key, value in self.repository.load_setting_values(
            self.writable_env_keys
        ).items():
            os.environ[key] = value
        for name, value in self.repository.load_extra_env():
            os.environ[name] = value

    @staticmethod
    def _sync_environment_value(name: str, value: str) -> None:
        """Sync one credential/custom env value to the running process."""
        normalized = value.strip()
        if normalized:
            os.environ[name] = normalized
        else:
            os.environ.pop(name, None)

    def _refresh_unavailable_sources(self) -> None:
        """Recompute connector availability after a secret setting changed."""
        settings = load_settings(self.settings_path)
        self.unavailable_sources = self._detect_unavailable_sources(
            self._registry,
            settings.sources,
        )
        self.repository.set_unavailable_sources(self.unavailable_sources)

    def _settings_payload(self) -> Mapping[str, Any]:
        provider_field_keys = [
            field["env"]
            for provider in self.provider_catalog
            for field in provider["fields"]
        ]
        field_statuses = self.repository.setting_status(provider_field_keys)
        providers = []
        for provider in self.provider_catalog:
            fields = []
            for field in provider["fields"]:
                status = field_statuses.get(
                    field["env"],
                    {"configured": False, "hint": ""},
                )
                fields.append(
                    {
                        **field,
                        "configured": status["configured"],
                        "hint": status["hint"],
                    }
                )
            providers.append({**provider, "fields": fields})
        stored_extra = self.repository.load_extra_env()
        extra_keys = [
            EXTRA_ENV_PREFIX + name for name, _ in stored_extra
        ]
        extra_statuses = self.repository.setting_status(extra_keys)
        extra_env = [
            {
                "name": name,
                "configured": extra_statuses[EXTRA_ENV_PREFIX + name][
                    "configured"
                ],
                "hint": extra_statuses[EXTRA_ENV_PREFIX + name]["hint"],
            }
            for name, _ in stored_extra
        ]
        return {
            "page_size": int(self.repository.setting("page_size", "25")),
            "providers": providers,
            "extra_env": extra_env,
        }

    def _bootstrap(self, query: Mapping[str, Sequence[str]]) -> Mapping[str, Any]:
        selected_text = _first(query, "date")
        zone = resolve_timezone(_first(query, "timezone"))
        selected_date = (
            date.fromisoformat(selected_text)
            if selected_text
            else datetime.now(zone).date()
        )
        lists = [dict(record) for record in self.repository.fixed_lists()]
        companies = self.repository.companies()
        counts = self.repository.counts(selected_date, timezone_name=zone.key)
        for list_record in lists:
            slug = str(list_record["slug"])
            list_record["company_count"] = sum(slug in company["list_slugs"] for company in companies)
            list_record["unread_count"] = counts["list_unread"].get(slug, 0)
        statuses = self.repository.source_statuses()
        return {
            "selected_date": selected_date.isoformat(),
            "display_date": f"{selected_date.strftime('%b')} {selected_date.day}, {selected_date.year}",
            "timezone": zone.key,
            "timezone_label": zone.key,
            "lists": lists,
            "companies": companies,
            "counts": counts,
            "sources": statuses,
            "topbar_summary": _topbar_summary(statuses),
            "settings": {"page_size": int(self.repository.setting("page_size", "25"))},
        }

    def _feed(self, query: Mapping[str, Sequence[str]]) -> Mapping[str, Any]:
        filters = _filters_from_mapping({key: values[-1] for key, values in query.items()})
        result = self.repository.query_feed_display(filters)
        disconnected = None
        available_types = set(self.repository.available_source_types())
        if filters.information_type == "news" and "news" not in available_types:
            disconnected = "News source not connected"
        elif filters.information_type == "community" and "community" not in available_types:
            disconnected = "Community source not connected"
        elif filters.information_type == "research" and "research" not in available_types:
            disconnected = "Research source not connected"
        return {
            "items": list(result.items),
            "pagination": {
                "page": result.page,
                "page_size": result.page_size,
                "pages": result.pages,
                "total": result.total,
            },
            "disconnected_message": disconnected,
            "active_filters": _filter_dict(filters),
        }

    def _html(self, path: str) -> WebResponse:
        template = (self.static_root / "index.html").read_text(encoding="utf-8")
        view = _view_for_path(path)
        html = template.replace("{{VIEW}}", view).replace("{{PATH}}", path)
        return WebResponse(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _static(self, path: str) -> WebResponse:
        relative = path.removeprefix("/static/")
        if relative not in {"app.css", "app.js"}:
            return self._json({"error": "Not found"}, 404)
        asset = self.static_root / relative
        content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
        return WebResponse(200, asset.read_bytes(), f"{content_type}; charset=utf-8")

    @staticmethod
    def _json(payload: Mapping[str, Any], status: int = 200) -> WebResponse:
        return WebResponse(status, json.dumps(payload).encode("utf-8"))


class DailyCollectionScheduler:
    """Run one incremental collection per Eastern calendar day."""

    def __init__(
        self,
        application: WebApplication,
        *,
        hour_et: int = 6,
        lookback_days: int = 7,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not 0 <= hour_et <= 23:
            raise ValueError("hour_et must be between 0 and 23")
        if lookback_days < 1:
            raise ValueError("lookback_days must be at least 1")
        self._application = application
        self._hour_et = hour_et
        self._lookback_days = lookback_days
        self._clock = clock
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="daily-information-collection",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def run_due_now(self, now: Optional[datetime] = None) -> bool:
        current = now or self._clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        today_et = current.astimezone(EASTERN).date()
        if self._application.repository.last_daily_sync_date() == today_et:
            return False
        summary = self._application.collect_active_companies(
            lookback_days=self._lookback_days,
            today=today_et,
        )
        self._application.repository.mark_daily_sync_attempt(today_et)
        LOGGER.info(
            "daily collection status=%s tickers=%d fetched=%d inserted=%d updated=%d",
            summary["status"],
            len(summary["tickers"]),
            summary["records_fetched"],
            summary["inserted"],
            summary["updated"],
        )
        return True

    def seconds_until_next_run(self, now: Optional[datetime] = None) -> float:
        current = now or self._clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current_et = current.astimezone(EASTERN)
        candidate = datetime.combine(
            current_et.date(), time(hour=self._hour_et), tzinfo=EASTERN
        )
        if candidate <= current_et:
            tomorrow = date.fromordinal(current_et.date().toordinal() + 1)
            candidate = datetime.combine(
                tomorrow, time(hour=self._hour_et), tzinfo=EASTERN
            )
        return max(1.0, (candidate.astimezone(timezone.utc) - current).total_seconds())

    def _run(self) -> None:
        try:
            self.run_due_now()
            while not self._stop_event.wait(self.seconds_until_next_run()):
                self.run_due_now()
        except Exception:
            LOGGER.exception("Daily collection scheduler stopped unexpectedly")


class InvestmentMonitorHandler(BaseHTTPRequestHandler):
    application: WebApplication

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch()

    def _dispatch(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        response = self.application.handle(self.command, self.path, body)
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "max-age=60")
        self.end_headers()
        self.wfile.write(response.body)

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), format % args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Investment Monitor web interface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    return parser


def main(arguments: Optional[Sequence[str]] = None) -> None:
    parsed = build_parser().parse_args(arguments)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    application = WebApplication(parsed.project_root)
    InvestmentMonitorHandler.application = application
    server = ThreadingHTTPServer((parsed.host, parsed.port), InvestmentMonitorHandler)
    scheduler: Optional[DailyCollectionScheduler] = None
    if _environment_bool("AUTO_DAILY_COLLECTION", True):
        scheduler = DailyCollectionScheduler(
            application,
            hour_et=_environment_int(
                "DAILY_COLLECTION_HOUR_ET", 6, minimum=0, maximum=23
            ),
            lookback_days=_environment_int(
                "DAILY_COLLECTION_LOOKBACK_DAYS", 7, minimum=1, maximum=365
            ),
        )
        scheduler.start()
    print(f"Investment Monitor running at http://{parsed.host}:{parsed.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if scheduler is not None:
            scheduler.stop()
        server.server_close()


def _decode_json(body: bytes) -> Mapping[str, Any]:
    payload = json.loads(body.decode("utf-8") or "{}")
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


def _first(query: Mapping[str, Sequence[str]], key: str) -> Optional[str]:
    values = query.get(key)
    return values[-1] if values else None


def _query_date(query: Mapping[str, Sequence[str]], key: str) -> Optional[date]:
    value = _first(query, key)
    return date.fromisoformat(value) if value else None


def _required_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a JSON boolean")
    return value


def _topbar_summary(
    statuses: Sequence[Mapping[str, Any]],
) -> Mapping[str, str]:
    """Build a short multi-source health summary for the top bar.

    Cards cover enabled/implemented content types; disabled placeholders
    (``not_connected`` without a provider) are ignored. Worst-status level
    drives the CSS class: failed/unavailable/temporarily_unavailable (4-5) >
    stale (3) > connected (2) > not_connected (1, renders failed since no
    source is usable).
    """
    cards = [
        status
        for status in statuses
        if status.get("type") in {"Filings", "News", "Community", "Research"}
        and (
            status.get("provider")
            or status.get("status") != "not_connected"
        )
    ]
    if not cards:
        return {"text": "Sources unavailable", "level": "failed"}
    level = max(
        TOPBAR_STATUS_LEVELS.get(str(card.get("status")), 4)
        for card in cards
    )

    def label(card: Mapping[str, Any]) -> str:
        return str(card.get("provider") or card.get("type") or "")
    if all(str(card.get("status")) == "connected" for card in cards):
        text = "Sources up to date · " + ", ".join(label(card) for card in cards)
    elif all(
        str(card.get("status"))
        in {
            "not_connected",
            "unavailable",
            "temporarily_unavailable",
            "failed",
        }
        for card in cards
    ):
        text = "Sources unavailable / Not connected"
    else:
        text = "Sources: " + " · ".join(
            f"{label(card)} "
            f"{TOPBAR_STATUS_WORDS.get(str(card.get('status')), str(card.get('status')))}"
            for card in cards
        )
    level_class = (
        "failed"
        if level >= 4 or level <= 1
        else "stale"
        if level == 3
        else "connected"
    )
    return {"text": text, "level": level_class}


def _filters_from_mapping(values: Mapping[str, Any]) -> FeedFilters:
    def parsed_date(key: str) -> Optional[date]:
        value = values.get(key)
        return date.fromisoformat(str(value)) if value else None

    return FeedFilters(
        list_slug=str(values["list"]) if values.get("list") else None,
        ticker=str(values["ticker"]) if values.get("ticker") else None,
        information_type=str(values.get("type") or "all"),
        form_type=str(values["form"]) if values.get("form") else None,
        start_date=parsed_date("start_date"),
        end_date=parsed_date("end_date"),
        read_state=str(values.get("read") or "all"),
        amendment=str(values.get("amendment") or "all"),
        query=str(values["q"]) if values.get("q") else None,
        page=int(values.get("page") or 1),
        page_size=int(values.get("page_size") or 25),
        timezone=str(values["timezone"]) if values.get("timezone") else None,
    )


def _filter_dict(filters: FeedFilters) -> Mapping[str, Any]:
    return {
        "list": filters.list_slug,
        "ticker": filters.ticker,
        "type": filters.information_type,
        "form": filters.form_type,
        "start_date": filters.start_date.isoformat() if filters.start_date else None,
        "end_date": filters.end_date.isoformat() if filters.end_date else None,
        "timezone": filters.timezone,
        "read": filters.read_state,
        "amendment": filters.amendment,
        "q": filters.query,
        "page": filters.page,
        "page_size": filters.page_size,
    }


def _view_for_path(path: str) -> str:
    if path in {"/", "/today"}:
        return "today"
    if path == "/information":
        return "information"
    if path == "/search":
        return "search"
    if path == "/activity":
        return "activity"
    if path == "/sources":
        return "sources"
    if path == "/settings":
        return "settings"
    return path.rsplit("/", 1)[-1]


def _environment_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _environment_int(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = os.environ.get(name)
    try:
        result = int(value) if value is not None else default
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result


def _empty_collection_summary(tickers: Sequence[str]) -> Mapping[str, Any]:
    return {
        "status": "empty",
        "tickers": list(tickers),
        "start_date": None,
        "end_date": None,
        "records_fetched": 0,
        "inserted": 0,
        "updated": 0,
        "failures": [],
    }


def _combine_collection_summaries(
    summaries: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if not summaries:
        return _empty_collection_summary(())
    statuses = {str(summary["status"]) for summary in summaries}
    if statuses == {"failure"}:
        status = "failure"
    elif "failure" in statuses or "partial" in statuses:
        status = "partial"
    elif "success" in statuses:
        status = "success"
    else:
        status = "empty"
    return {
        "status": status,
        "tickers": [
            ticker for summary in summaries for ticker in summary["tickers"]
        ],
        "start_date": min(
            str(summary["start_date"])
            for summary in summaries
            if summary["start_date"] is not None
        ),
        "end_date": max(
            str(summary["end_date"])
            for summary in summaries
            if summary["end_date"] is not None
        ),
        "records_fetched": sum(int(summary["records_fetched"]) for summary in summaries),
        "inserted": sum(int(summary["inserted"]) for summary in summaries),
        "updated": sum(int(summary["updated"]) for summary in summaries),
        "failures": [
            failure for summary in summaries for failure in summary["failures"]
        ],
    }


if __name__ == "__main__":
    main()
