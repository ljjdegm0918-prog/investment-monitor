"""Testable local HTTP application for the investment monitor web MVP."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
import mimetypes
import os
from pathlib import Path
import threading
import uuid
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
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
from .au_universe import au_universe_name_map
from .ca_universe import (
    CaUniverseError,
    ca_universe_name_map,
    load_ca_universe,
    refresh_ca_universe,
)
from .hk_universe import hk_universe_name_map
from .kr_universe import kr_universe_name_map
from .models import (
    ALLOWED_MARKETS,
    MARKET_AU,
    MARKET_CA,
    MARKET_FR,
    MARKET_BE,
    MARKET_DE,
    MARKET_HK,
    MARKET_KR,
    MARKET_ES,
    MARKET_SG,
    MARKET_CH,
    MARKET_PL,
    MARKET_SE,
    MARKET_AQ,
    MARKET_CXE,
    MARKET_EMF,
    MARKET_TRQ,
    MARKET_EUX,
    MARKET_EE,
    MARKET_LV,
    MARKET_LT,
    MARKET_NO,
    MARKET_PT,
    MARKET_AT,
    MARKET_IN,
    MARKET_MX,
    MARKET_IL,
    MARKET_HU,
    MARKET_IT,
    MARKET_NL,
    MARKET_TW,
    MARKET_UK,
    MARKET_UNKNOWN,
    MARKET_US,
)
from .tw_universe import tw_universe_name_map
from .universe.fr_universe import fr_universe_name_map
from .universe.de_universe import de_universe_name_map, refresh_de_universe
from .universe.be_universe import be_universe_name_map, refresh_be_universe
from .universe.nl_universe import nl_universe_name_map, refresh_nl_universe
from .universe.it_universe import it_universe_name_map, refresh_it_universe
from .universe.es_universe import es_universe_name_map
from .universe.sg_universe import load_sg_universe, sg_universe_name_map
from .universe.ch_universe import ch_universe_name_map
from .universe.pl_universe import pl_universe_name_map, refresh_pl_universe
from .universe.at_universe import at_universe_name_map, refresh_at_universe
from .universe.se_universe import se_universe_name_map
from .universe.aq_universe import aq_universe_name_map
from .universe.cxe_universe import cxe_universe_name_map
from .universe.emf_universe import emf_universe_name_map
from .universe.trq_universe import trq_universe_name_map
from .universe.eux_universe import eux_universe_name_map
from .universe.global_equity_reference import (
    DEFAULT_CACHE_PATH as GLOBAL_EQUITY_REFERENCE_CACHE_PATH,
    search_global_equity_reference,
)
from .universe.exchange_catalog import catalog_summary
from .universe.coverage_report import coverage_report
from .pipeline import CollectionEvent
from .registry import (
    SourceRegistry,
    create_default_registry,
    relevant_sources_for_market,
)
from .sources.companies_house import CompaniesHouseCompanyResolver
from .sources.dart import DARTCompanyResolver
from .sources.hkexnews import HKEXNewsCompanyResolver
from .sources.sec.client import SECConfigurationError
from .sources.sec.company_resolver import SECCompanyResolver
from .sqlite_repository import SQLiteInformationRepository
from .uk_universe import uk_universe_name_map
from .web_repository import (
    EXTRA_ENV_PREFIX,
    FeedFilters,
    REGISTERED_STUB_SOURCES,
    WebRepository,
    normalize_be_ticker,
    normalize_de_ticker,
    normalize_fr_ticker,
    normalize_it_ticker,
    normalize_nl_ticker,
)
from .company_import import group_by_market, parse_company_inputs
from .research import ResearchScope, ResearchSettings, card_from_json, validate_language
from .research_repository import CARD_STATUS_COMPLETED
from .research_service import ResearchService, validate_list_slug

LOGGER = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")
SHANGHAI = ZoneInfo("Asia/Shanghai")
CollectionRunner = Callable[..., ConfiguredCollectionResult]

# Add-company 回填源过滤依据（大脑拍板）：
# - 这些是注册 stub，collect() 恒返回空行，回填时跳过避免空转占队列；
# - xueqiu 仅在有可选 cookie 时才 LIVE，保留但永远排在 community 末尾。
ADD_COMPANY_BACKFILL_SKIP_SOURCES = frozenset(REGISTERED_STUB_SOURCES)
ADD_COMPANY_BACKFILL_COMMUNITY_TAIL = frozenset({"xueqiu"})
COMMUNITY_SOURCE_TYPE = "community"


def _warm_universe_on_first_add(
    market: str,
    loader: Callable[[], Mapping[str, Mapping[str, str]]],
    refresher: Callable[[], Mapping[str, Any]],
) -> Optional[Mapping[str, Mapping[str, str]]]:
    """Load a universe and make one best-effort refresh when its cache is cold."""
    universe = loader()
    if universe:
        return universe
    try:
        refresher()
    except Exception:
        LOGGER.warning(
            "%s_universe refresh failed on add-company; continuing without fallback",
            market,
            exc_info=True,
        )
    return loader() or None


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


_WEB_AUTH_REQUIRED_CODE = "web_auth_required"

# Backfill task resource bounds: keep at most this many terminal tasks in
# memory (LRU by finished_at) and run at most two backfills at once; extra
# requests queue on the semaphore instead of being dropped.
MAX_TERMINAL_BACKFILL_TASKS = 100
MAX_CONCURRENT_BACKFILLS = 2
BACKFILL_TERMINAL_STATUSES = frozenset({"success", "partial", "failure"})

# Security response headers applied to every HTTP response by the handler.
SECURITY_HEADERS = (
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "same-origin"),
    (
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'",
    ),
)


def _web_auth_rejection(
    path: str,
    headers: Optional[Mapping[str, Any]],
) -> Optional[WebResponse]:
    """Reject API requests that miss the configured bearer token.

    Authentication is only enforced for real HTTP requests (headers is not
    None) so internal ``self.handle(...)`` calls stay exempt. When
    ``WEB_AUTH_TOKEN`` is unset or empty, local development keeps the legacy
    no-auth behavior.
    """
    if headers is None or not path.startswith("/api/"):
        return None
    expected_token = os.environ.get("WEB_AUTH_TOKEN", "").strip()
    if not expected_token:
        return None
    authorization = _header_value(headers, "Authorization")
    expected = f"Bearer {expected_token}"
    if not hmac.compare_digest(authorization, expected):
        return WebResponse(
            401,
            json.dumps({
                "error": "Authorization required",
                "code": _WEB_AUTH_REQUIRED_CODE,
            }).encode("utf-8"),
        )
    return None


class WebApplication:
    """Pure request dispatcher used by both HTTP server and tests."""

    def __init__(
        self,
        project_root: Path,
        *,
        collection_runner: CollectionRunner = run_ticker_collection,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        # The clock is injectable so Daily Report default dates are testable
        # without monkeypatching ``datetime``; callers may omit it.
        self._clock = clock if clock is not None else (lambda: datetime.now(timezone.utc))
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
        self.research = ResearchService(
            self.repository,
            settings.database_path,
            ResearchSettings.from_environment(),
        )
        # DB/UI-stored secrets take priority over .env for this process.
        self._load_credentials_to_environment()
        self.unavailable_sources = self._detect_unavailable_sources(
            registry,
            settings.sources,
        )
        self.repository.set_unavailable_sources(self.unavailable_sources)
        self.repository.import_universe(load_universe(project_root / "config" / "universe.csv"))
        self._ensure_active_sync_states()
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
        companies_house_cache_path = (
            project_root
            / ".cache"
            / "investment_monitor"
            / "companies_house_numbers.json"
        )
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
        self.hkexnews_resolver = HKEXNewsCompanyResolver()
        self.static_root = Path(__file__).parent / "web_static"
        self._collection_runner = collection_runner
        self._collection_lock = threading.Lock()
        self._backfill_tasks: Dict[str, Dict[str, Any]] = {}
        self._backfill_tasks_lock = threading.Lock()
        self._backfill_semaphore = threading.BoundedSemaphore(
            MAX_CONCURRENT_BACKFILLS
        )

    def handle(
        self,
        method: str,
        target: str,
        body: bytes = b"",
        headers: Optional[Mapping[str, str]] = None,
    ) -> WebResponse:
        parsed = urlparse(target)
        query = parse_qs(parsed.query)
        try:
            rejection = _web_auth_rejection(parsed.path, headers)
            if rejection is not None:
                return rejection
            if method == "POST" and headers is not None:
                rejection = _same_origin_json_write_rejection(headers)
                if rejection is not None:
                    return rejection
            if method == "GET" and parsed.path == "/favicon.ico":
                return WebResponse(204, b"", "image/x-icon")
            if method == "GET" and parsed.path.startswith("/static/"):
                return self._static(parsed.path)
            if method == "GET" and (parsed.path in {
                "/", "/today", "/information", "/search", "/activity",
                "/sources", "/settings", "/manage", "/research",
            } or parsed.path.startswith("/lists/")):
                return self._html(parsed.path)
            if method == "GET" and parsed.path == "/api/bootstrap":
                return self._json(self._bootstrap(query))
            if method == "GET" and parsed.path == "/api/feed":
                return self._json(self._feed(query))
            if method == "GET" and parsed.path == "/api/daily":
                return self._json(self._daily(query))
            if method == "GET" and parsed.path == "/api/daily-range":
                return self._json(self._daily_range(query))
            if method == "GET" and parsed.path == "/api/companies":
                return self._json({"companies": self.repository.companies(_first(query, "list"))})
            if method == "GET" and parsed.path == "/api/companies/search":
                term = str(_first(query, "q") or "").strip()
                if len(term) < 1:
                    raise ValueError("Enter a company name or ticker")
                candidates = {
                    (str(record["ticker"]), str(record["market"])): dict(record)
                    for record in self.resolver.search(term)
                }
                for record in self.repository.search_companies(term):
                    candidates[(str(record["ticker"]), str(record["market"]))] = dict(record)
                return self._json({"candidates": list(candidates.values())[:20]})
            if method == "GET" and parsed.path == "/api/activity":
                return self._json(self.repository.activity(
                    source=_first(query, "source"),
                    status=_first(query, "status"),
                    start_date=_query_date(query, "start_date"),
                    end_date=_query_date(query, "end_date"),
                ))
            if method == "GET" and parsed.path == "/api/sources":
                return self._json({"sources": self.repository.connector_statuses()})
            if method == "GET" and parsed.path.startswith("/api/backfill-tasks/"):
                task_id = parsed.path[len("/api/backfill-tasks/"):]
                task = self._backfill_task_payload(task_id)
                if task is None:
                    return self._json({"error": "Backfill task not found"}, 404)
                return self._json(task)
            if method == "GET" and parsed.path == "/api/research/model":
                return self._json({"model": self.research.model_status()})
            if method == "GET" and parsed.path == "/api/research/companies":
                list_slug = _first(query, "list") or None
                try:
                    list_slug = validate_list_slug(list_slug)
                except ValueError:
                    return self._json(
                        {"error": "list must be one of: all, holdings, planned, watchlist"},
                        400,
                    )
                language = _fallback_language(_first(query, "language"))
                scope = self._research_scope(
                    _query_date(query, "start_date"),
                    _query_date(query, "end_date"),
                    list_slug,
                )
                return self._json({
                    "companies": self.research.companies(scope, language),
                    "model": self.research.model_status(),
                    "start_date": scope.start_date.isoformat(),
                    "end_date": scope.end_date.isoformat(),
                    "list": list_slug,
                })
            if method == "GET" and parsed.path.startswith("/api/research/cards/"):
                card_id = _trailing_id(parsed.path, "/api/research/cards/")
                card = self.research.card(card_id)
                if card is None:
                    return self._json({"error": "Card not found"}, 404)
                # Only a completed card is printable. Failed or still-generating
                # cards (and their error codes) must never be exposed here.
                if card.get("status") != CARD_STATUS_COMPLETED:
                    return self._json({"error": "Card not found"}, 404)
                company_id = int(card["company_id"])
                if not self.repository.company_in_research_lists(company_id):
                    return self._json({"error": "Card not found"}, 404)
                company = self.repository.company_identity(company_id)
                return self._json(_research_card_payload(card, company))
            if method == "POST" and parsed.path == "/api/research/generate":
                payload = _decode_json(body)
                company_id = int(payload["company_id"])
                language = validate_language(payload.get("language") or "en")
                force = _optional_bool(payload, "force", False)
                list_slug = validate_list_slug(payload.get("list"))
                scope = self._research_scope(
                    _payload_date(payload, "start_date"),
                    _payload_date(payload, "end_date"),
                    list_slug,
                )
                result = self.research.generate(company_id, language, scope, force)
                status_code = 202 if result["status"] == "generating" else 200
                return self._json(result, status_code)
            if method == "GET" and parsed.path.startswith("/api/research/generations/"):
                generation_id = _trailing_id(
                    parsed.path, "/api/research/generations/"
                )
                status = self.research.generation_status(generation_id)
                if status is None:
                    return self._json({"error": "Generation not found"}, 404)
                return self._json(status)
            if method == "POST" and parsed.path == "/api/lists":
                payload = _decode_json(body)
                return self._json(
                    {"list": self.repository.create_list(str(payload.get("name") or ""))},
                    201,
                )
            if method == "POST" and parsed.path == "/api/lists/rename":
                payload = _decode_json(body)
                return self._json({"list": self.repository.rename_list(
                    str(payload.get("slug") or ""), str(payload.get("name") or "")
                )})
            if method == "POST" and parsed.path == "/api/lists/delete":
                payload = _decode_json(body)
                return self._json({"deleted": self.repository.delete_list(
                    str(payload.get("slug") or "")
                )})
            if method == "POST" and parsed.path == "/api/companies/batch":
                payload = _decode_json(body)
                default_market = str(payload.get("market") or MARKET_US).strip().lower()
                if default_market not in ALLOWED_MARKETS:
                    return self._json(
                        {
                            "error": "market must be one of: "
                            + ", ".join(sorted(ALLOWED_MARKETS))
                        },
                        400,
                    )
                raw_tickers = str(payload.get("tickers", ""))
                list_slugs = tuple(payload.get("lists") or ())
                parsed = parse_company_inputs(raw_tickers, default_market)
                if not parsed:
                    return self._json({"error": "Enter at least one ticker"}, 400)
                added = []
                already_present = []
                failed = []
                for market, items in group_by_market(parsed):
                    tickers = tuple(item.ticker for item in items)
                    resolver = self._resolver_for(market)
                    name_fallback = self._name_fallback_for(market)
                    name_fallback = self._with_global_reference_fallback(
                        market,
                        name_fallback,
                    )
                    try:
                        result = dict(self.repository.add_companies_batch(
                            " ".join(tickers),
                            list_slugs,
                            resolver,
                            market=market,
                            name_fallback=name_fallback,
                        ))
                    except ValueError as error:
                        failed.append(
                            {"ticker": " ".join(tickers), "error": str(error)}
                        )
                        continue
                    added.extend(result["added"])
                    already_present.extend(result["already_present"])
                    failed.extend(result["failed"])
                    added_tickers = tuple(
                        str(record["ticker"]) for record in result["added"]
                    )
                    if added_tickers:
                        relevant_sources = self._relevant_sources(market)
                        self.repository.ensure_source_ticker_sync_states(tuple(
                            (source, ticker, market)
                            for source in relevant_sources
                            for ticker in added_tickers
                        ))
                markets_map = {
                    str(record["ticker"]): str(record["market"])
                    for record in added
                }
                response = {
                    "added": added,
                    "already_present": already_present,
                    "failed": failed,
                    "parsed": [
                        {
                            "ticker": item.ticker,
                            "market": item.market,
                            "explicit_suffix": item.explicit_suffix,
                        }
                        for item in parsed
                    ],
                    "groups": [
                        {"market": market, "tickers": [item.ticker for item in items]}
                        for market, items in group_by_market(parsed)
                    ],
                    "collection": None,
                }
                if markets_map:
                    task_id = f"bf-{uuid.uuid4()}"
                    self._register_backfill_task(
                        task_id, markets_map, default_market
                    )
                    threading.Thread(
                        target=self._run_add_company_backfill,
                        args=(task_id, markets_map, default_market),
                        daemon=True,
                    ).start()
                    response["backfill_task_id"] = task_id
                    response["backfill_status"] = "queued"
                else:
                    response["backfill_task_id"] = None
                    response["backfill_status"] = "completed"
                return self._json(response, 201)
            if method == "POST" and parsed.path == "/api/companies/csv":
                payload = _decode_json(body)
                return self._json(
                    self._add_companies_csv(str(payload.get("csv", ""))),
                    201,
                )
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
            if method == "GET" and parsed.path == "/api/coverage":
                # Independent per-country information-source coverage board.
                # The static venue benchmark is not a broker integration.
                try:
                    return self._json({
                        "catalog": catalog_summary(),
                        "report": coverage_report(),
                        "canada": self.repository.canada_coverage_metrics(
                            load_ca_universe(
                                self.project_root / ".cache"
                                / "investment_monitor" / "ca_universe.json"
                            )
                        ),
                        "singapore": self.repository.singapore_coverage_metrics(
                            load_sg_universe(
                                self.project_root / ".cache"
                                / "investment_monitor" / "sg_universe.json"
                            )
                        ),
                    })
                except Exception:  # noqa: BLE001 - 目录损坏要给出 500 而不是空表
                    LOGGER.exception("coverage payload failed")
                    return self._json(
                        {"error": "Coverage data is unavailable"}, 500
                    )
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

    def _add_companies_csv(self, raw_csv: str) -> Mapping[str, Any]:
        """Import mixed-market rows through the same path as manual adds."""
        entries, parse_failures = _parse_company_csv(
            raw_csv,
            self.repository.fixed_lists(),
        )
        groups: Dict[Tuple[str, Tuple[str, ...]], List[Mapping[str, Any]]] = {}
        for entry in entries:
            key = (str(entry["market"]), tuple(entry["lists"]))
            groups.setdefault(key, []).append(entry)

        added: List[Mapping[str, Any]] = []
        already_present: List[Mapping[str, Any]] = []
        failed: List[Mapping[str, Any]] = list(parse_failures)
        collection_summaries: List[Mapping[str, Any]] = []
        for (market, lists), group in groups.items():
            tickers = "\n".join(str(entry["ticker"]) for entry in group)
            response = self.handle(
                "POST",
                "/api/companies/batch",
                json.dumps({
                    "tickers": tickers,
                    "lists": list(lists),
                    "market": market,
                }).encode(),
            )
            payload = json.loads(response.body.decode("utf-8"))
            if response.status >= 400:
                for entry in group:
                    failed.append({
                        "row": entry["row"],
                        "ticker": entry["ticker"],
                        "error": str(payload.get("error") or "Import failed"),
                    })
                continue

            row_by_ticker: Dict[str, int] = {}
            for entry in group:
                parsed_entries = parse_company_inputs(str(entry["ticker"]), market)
                normalized = parsed_entries[0].ticker if parsed_entries else str(entry["ticker"])
                row_by_ticker[normalized] = int(entry["row"])
            for target, records in (
                (added, payload.get("added") or ()),
                (already_present, payload.get("already_present") or ()),
                (failed, payload.get("failed") or ()),
            ):
                for record in records:
                    enriched = dict(record)
                    row = row_by_ticker.get(str(record.get("ticker") or ""))
                    if row is not None:
                        enriched["row"] = row
                    target.append(enriched)
            if payload.get("collection"):
                collection_summaries.append(payload["collection"])

        result: Dict[str, Any] = {
            "added": added,
            "already_present": already_present,
            "failed": sorted(failed, key=lambda item: int(item.get("row", 0))),
        }
        if collection_summaries:
            result["collection"] = _combine_collection_summaries(
                collection_summaries
            )
        return result

    def collect_tickers(
        self,
        tickers: Sequence[str],
        *,
        lookback_days: int,
        today: Optional[date] = None,
        markets: Optional[Mapping[str, str]] = None,
        sources: Optional[Iterable[str]] = None,
        initial_backfill: bool = False,
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
        selected_sources = None if sources is None else tuple(sources)
        with self._collection_lock:
            try:
                result = self._collection_runner(
                    tickers=normalized,
                    settings_path=self.settings_path,
                    start_date=start_date,
                    end_date=end_date,
                    markets=market_map,
                    sources=selected_sources,
                    initial_backfill=initial_backfill,
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                LOGGER.exception("Collection setup failed for %s", ", ".join(normalized))
                self._record_setup_failures(
                    normalized,
                    message,
                    sources=selected_sources,
                    markets=market_map,
                    start_date=start_date,
                    end_date=end_date,
                    initial_backfill=initial_backfill,
                )
                return {
                    "status": "failure",
                    "tickers": list(normalized),
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "records_fetched": 0,
                    "inserted": 0,
                    "updated": 0,
                    "failures": [
                        {
                            "source": "collection_setup",
                            "ticker": ticker,
                            "message": message,
                        }
                        for ticker in normalized
                    ],
                }
        failures = [
            {
                "source": failure.source,
                "ticker": failure.ticker,
                "message": failure.message,
                **({"feed": failure.feed} if failure.feed else {}),
                **({"url": failure.url} if failure.url else {}),
            }
            for failure in result.failures
        ]
        event_statuses = tuple(event.status for event in result.events)
        if event_statuses:
            status = (
                "partial"
                if "partial" in event_statuses
                or (
                    "failure" in event_statuses
                    and any(value != "failure" for value in event_statuses)
                )
                else "failure" if set(event_statuses) == {"failure"}
                else "success" if "success" in event_statuses
                else "empty"
            )
        else:
            status = (
                "partial" if result.items and failures
                else "success" if result.items
                else "failure" if failures
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
        incremental: Dict[Tuple[str, str], List[str]] = {}
        source_tickers = []
        for ticker, market in active_companies:
            for source in self._relevant_sources(market):
                source_tickers.append((source, ticker, market))
                incremental.setdefault((source, market), []).append(ticker)
        self.repository.ensure_source_ticker_sync_states(tuple(source_tickers))
        summaries = []
        for (source, market), tickers in sorted(incremental.items()):
            normalized_tickers = tuple(sorted(set(tickers)))
            summaries.append(self.collect_tickers(
                normalized_tickers,
                lookback_days=lookback_days,
                today=today,
                markets={ticker: market for ticker in normalized_tickers},
                sources=(source,),
                initial_backfill=False,
            ))
        return _combine_collection_summaries(summaries)

    def _relevant_sources(self, market: str) -> Tuple[str, ...]:
        return relevant_sources_for_market(self.enabled_sources, market)

    def _add_company_backfill_sources(self, market: str) -> Tuple[str, ...]:
        """Return add-company backfill sources, filtered and ordered.

        从 self._relevant_sources(market) 出发（保持 enabled_sources 原有顺序），
        然后：
        - 永远排除注册 stub（collect() 恒空）；
        - filings/disclosure/news 等非 community 源排在前段，LIVE community
          源排在后段；xueqiu 保留但强制放在 community 末尾。
        分类依据是 settings 里每个 source 的 source_type；无 source_type 或
        归属不清的一律视为非 community（放前段），不凭名字猜测。
        """
        source_types = {
            source.name: str(source.source_type)
            for source in self.source_catalog
        }
        front: List[str] = []
        community: List[str] = []
        tail: List[str] = []
        for source in self._relevant_sources(market):
            if source in ADD_COMPANY_BACKFILL_SKIP_SOURCES:
                continue
            if source in ADD_COMPANY_BACKFILL_COMMUNITY_TAIL:
                tail.append(source)
            elif source_types.get(source) == COMMUNITY_SOURCE_TYPE:
                community.append(source)
            else:
                front.append(source)
        return tuple(front + community + tail)

    def _register_backfill_task(
        self,
        task_id: str,
        markets_map: Mapping[str, str],
        default_market: str,
    ) -> Dict[str, Any]:
        """Create the in-memory add-company backfill task in the queued state."""
        task = {
            "id": task_id,
            "status": "queued",
            "tickers": list(markets_map.keys()),
            "market": default_market,
            "markets": dict(markets_map),
            "sources": None,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "summary": None,
        }
        with self._backfill_tasks_lock:
            self._backfill_tasks[task_id] = task
        return task

    def _set_backfill_task(self, task_id: str, **updates: Any) -> None:
        terminal = False
        with self._backfill_tasks_lock:
            task = self._backfill_tasks.get(task_id)
            if task is not None:
                task.update(updates)
                terminal = task.get("status") in BACKFILL_TERMINAL_STATUSES
        if terminal:
            self._prune_backfill_tasks()

    def _prune_backfill_tasks(self) -> None:
        """Drop oldest terminal tasks so memory stays bounded (LRU cap)."""
        with self._backfill_tasks_lock:
            terminal_tasks = [
                (task_id, task)
                for task_id, task in self._backfill_tasks.items()
                if task.get("status") in BACKFILL_TERMINAL_STATUSES
            ]
            excess = len(terminal_tasks) - MAX_TERMINAL_BACKFILL_TASKS
            if excess <= 0:
                return
            terminal_tasks.sort(
                key=lambda pair: (pair[1].get("finished_at") or "", pair[0])
            )
            for task_id, _task in terminal_tasks[:excess]:
                self._backfill_tasks.pop(task_id, None)

    def _backfill_task_payload(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._backfill_tasks_lock:
            task = self._backfill_tasks.get(task_id)
        return dict(task) if task is not None else None

    def _run_add_company_backfill(
        self,
        task_id: str,
        markets_map: Mapping[str, str],
        default_market: str,
    ) -> None:
        """Backfill newly added companies (across markets) in a background thread."""
        del default_market  # markets_map 已含每个 ticker 的市场，无需再按默认市场分组
        market_tickers: Dict[str, List[str]] = {}
        for ticker, market in markets_map.items():
            market_tickers.setdefault(market, []).append(ticker)
        sources: List[str] = []
        for market in market_tickers:
            for source in self._add_company_backfill_sources(market):
                if source not in sources:
                    sources.append(source)

        with self._backfill_semaphore:
            self._run_backfill_locked(task_id, market_tickers, sources)

    def _run_backfill_locked(
        self,
        task_id: str,
        market_tickers: Mapping[str, List[str]],
        sources: List[str],
    ) -> None:
        """Run one backfill while holding a slot of the concurrency budget."""
        self._set_backfill_task(
            task_id,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            sources=sources,
        )
        try:
            lookback_days = _environment_int(
                "ADD_COMPANY_BACKFILL_DAYS",
                30,
                minimum=1,
                maximum=3650,
            )
            summaries = []
            for market, tickers in market_tickers.items():
                tickers_tuple = tuple(tickers)
                for source in self._add_company_backfill_sources(market):
                    summaries.append(self.collect_tickers(
                        tickers_tuple,
                        lookback_days=lookback_days,
                        markets={ticker: market for ticker in tickers_tuple},
                        sources=(source,),
                        initial_backfill=True,
                    ))
            summary = _combine_collection_summaries(tuple(summaries))
        except Exception as error:
            LOGGER.exception("Add-company backfill %s failed", task_id)
            status = "failure"
            error_message = str(error) or error.__class__.__name__
            summary = _empty_collection_summary(tuple(markets_map.keys()))
        else:
            combined_status = str(summary.get("status"))
            if combined_status == "failure":
                status = "failure"
            elif combined_status == "partial":
                status = "partial"
            else:
                status = "success"
            failures = summary.get("failures") or []
            error_message = (
                "; ".join(
                    f"{failure.get('source', 'unknown')}: "
                    f"{failure.get('ticker', '?')}: "
                    f"{failure.get('message', '')}"
                    for failure in failures
                )
                if failures
                else None
            )
        self._set_backfill_task(
            task_id,
            status=status,
            finished_at=datetime.now(timezone.utc).isoformat(),
            error=error_message,
            summary=summary,
        )

    def _ensure_active_sync_states(self) -> None:
        source_tickers = tuple(
            (source, ticker, market)
            for ticker, market in self.repository.active_companies()
            for source in self._relevant_sources(market)
        )
        self.repository.ensure_source_ticker_sync_states(source_tickers)

    def _record_setup_failures(
        self,
        tickers: Sequence[str],
        message: str,
        *,
        sources: Optional[Sequence[str]] = None,
        markets: Optional[Mapping[str, str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        initial_backfill: bool = False,
    ) -> None:
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
                market=str((markets or {}).get(ticker) or MARKET_US),
                requested_start_date=start_date,
                requested_end_date=end_date,
                effective_start_date=start_date,
                effective_end_date=end_date,
                coverage_kind="unknown",
                initial_backfill=initial_backfill,
            )
            for source in (sources if sources is not None else self.enabled_sources)
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
        if market == MARKET_TW:
            # TW disclosure mapping is not connected yet; never let SEC map
            # a Taiwan code to a same-named US company.
            return None
        if market == MARKET_AU:
            # AU companies stay unmapped; never let SEC map an Australian
            # symbol to a same-named US company.
            return None
        if market == MARKET_BE:
            # BE stays unmapped via SEC; disclosure matches by ISIN/name from
            # the universe, never by pretending an SEC CIK exists.
            return None
        if market == MARKET_FR:
            # FR stays unmapped via SEC; AMF OAM matches by company name /
            # universe, never by pretending an SEC CIK exists.
            return None
        if market == MARKET_DE:
            # DE stays unmapped via SEC; EQS matches by ISIN from the universe,
            # never by pretending an SEC CIK exists.
            return None
        if market == MARKET_NL:
            # NL stays unmapped via SEC; disclosure matches by ISIN/name from
            # the universe, never by pretending an SEC CIK exists.
            return None
        if market == MARKET_IT:
            # IT stays unmapped via SEC; disclosure matches by ISIN/name from
            # the universe, never by pretending an SEC CIK exists.
            return None
        if market == MARKET_ES:
            # ES stays unmapped via SEC; disclosure matches by ISIN/name from
            # the universe, never by pretending an SEC CIK exists.
            return None
        if market == MARKET_SG:
            # SG stays unmapped via SEC; disclosure matches by stock code /
            # name / ISIN from the universe, never by pretending an SEC CIK
            # exists.
            return None
        if market == MARKET_CH:
            # CH stays unmapped via SEC; disclosure matches by ISIN/name
            # from the universe, never by pretending an SEC CIK exists.
            return None
        if market == MARKET_PL:
            # PL stays unmapped via SEC; disclosure matches by ISIN/name
            # from the universe, never by pretending an SEC CIK exists.
            return None
        if market == MARKET_SE:
            # SE stays unmapped via SEC; disclosure matches by ISIN/name
            # from the universe, never by pretending an SEC CIK exists.
            return None
        if market == MARKET_AQ:
            # AQ stays unmapped via SEC; never let SEC map an Aquis symbol
            # to a same-named US company.
            return None
        if market == MARKET_CXE:
            # CXE stays unmapped via SEC; never let SEC map a Cboe Europe
            # symbol to a same-named US company.
            return None
        if market == MARKET_EMF:
            # EMF stays unmapped via SEC; funds are identified by ISIN,
            # never by pretending an SEC CIK exists.
            return None
        if market == MARKET_TRQ:
            # TRQ stays unmapped via SEC; never let SEC map a Turquoise
            # symbol to a same-named US company.
            return None
        if market == MARKET_EUX:
            # EUX stays unmapped via SEC; Eurex derivatives are product
            # codes, never SEC CIKs.
            return None
        if market in (MARKET_EE, MARKET_LV, MARKET_LT):
            # Baltic companies stay unmapped; Nasdaq Baltic disclosures are
            # matched by ISIN/name from the Baltic universe, never SEC CIKs.
            return None
        if market in (MARKET_NO, MARKET_PT):
            # Oslo/Lisbon companies stay unmapped; disclosure matching is
            # by ISIN/name from the local Euronext universe, never SEC CIKs.
            return None
        if market == MARKET_AT:
            # Vienna companies stay unmapped; never let SEC map an Austrian
            # symbol to a same-named US company.
            return None
        if market == MARKET_IN:
            # Indian companies stay unmapped; NSE announcements carry their
            # own symbol/ISIN and never need an SEC CIK.
            return None
        if market == MARKET_MX:
            # Mexican companies stay unmapped; never let SEC map a BMV
            # symbol to a same-named US company.
            return None
        if market == MARKET_IL:
            # Israeli companies stay unmapped; TASE/MAYA announcements carry
            # their own symbol/ISIN and never need an SEC CIK.
            return None
        if market == MARKET_HU:
            # Hungarian companies stay unmapped; BSE/BET announcements carry
            # their own symbol/ISIN and never need an SEC CIK.
            return None
        if market == MARKET_CA:
            # CA disclosure mapping is not connected yet; never let SEC map
            # a Canadian symbol to a same-named US company.
            return None
        if market in (MARKET_US, MARKET_UNKNOWN):
            return self.resolver
        # Every other declared market keeps its own identity. This also
        # protects newly added markets from accidentally resolving a
        # same-named US ticker before a market-specific resolver is wired.
        return None

    def _name_fallback_for(
        self,
        market: str,
    ) -> Optional[Mapping[str, Mapping[str, str]]]:
        """Load the universe name fallback for a market, or None.

        Extracted from the batch-add route so mixed-market adds reuse the exact
        same per-market universe warm-up logic (including the one-time refreshes
        for BE/DE/NL/IT/PL and the guarded CA refresh).
        """
        if market == MARKET_KR:
            return kr_universe_name_map()
        if market == MARKET_UK:
            return uk_universe_name_map()
        if market == MARKET_HK:
            return hk_universe_name_map()
        if market == MARKET_TW:
            return tw_universe_name_map()
        if market == MARKET_AU:
            return au_universe_name_map()
        if market == MARKET_BE:
            return _warm_universe_on_first_add(
                market,
                be_universe_name_map,
                refresh_be_universe,
            )
        if market == MARKET_FR:
            return fr_universe_name_map()
        if market == MARKET_DE:
            return _warm_universe_on_first_add(
                market,
                de_universe_name_map,
                refresh_de_universe,
            )
        if market == MARKET_NL:
            return _warm_universe_on_first_add(
                market,
                nl_universe_name_map,
                refresh_nl_universe,
            )
        if market == MARKET_IT:
            return _warm_universe_on_first_add(
                market,
                it_universe_name_map,
                refresh_it_universe,
            )
        if market == MARKET_ES:
            name_fallback = es_universe_name_map()
            if not name_fallback:
                LOGGER.warning(
                    "es_universe cache is cold on add-company; "
                    "synchronous refresh skipped because ticker enrichment "
                    "can take several minutes"
                )
            return name_fallback
        if market == MARKET_SG:
            return sg_universe_name_map()
        if market == MARKET_CH:
            return ch_universe_name_map()
        if market == MARKET_PL:
            return _warm_universe_on_first_add(
                market,
                pl_universe_name_map,
                refresh_pl_universe,
            )
        if market == MARKET_SE:
            return se_universe_name_map()
        if market == MARKET_AQ:
            return aq_universe_name_map()
        if market == MARKET_CXE:
            return cxe_universe_name_map()
        if market == MARKET_EMF:
            return emf_universe_name_map()
        if market == MARKET_TRQ:
            return trq_universe_name_map()
        if market == MARKET_EUX:
            return eux_universe_name_map()
        if market in (MARKET_EE, MARKET_LV, MARKET_LT):
            from .universe.nasdaq_baltic_universe import baltic_universe_name_map
            return baltic_universe_name_map(market)
        if market == MARKET_NO:
            from .universe.no_universe import no_universe_name_map
            return no_universe_name_map()
        if market == MARKET_PT:
            from .universe.pt_universe import pt_universe_name_map
            return pt_universe_name_map()
        if market == MARKET_AT:
            return _warm_universe_on_first_add(
                market,
                at_universe_name_map,
                refresh_at_universe,
            )
        if market == MARKET_IN:
            from .universe.in_universe import in_universe_name_map
            return in_universe_name_map()
        if market == MARKET_MX:
            from .universe.mx_universe import mx_universe_name_map
            return mx_universe_name_map()
        if market == MARKET_IL:
            from .universe.il_universe import il_universe_name_map
            return il_universe_name_map()
        if market == MARKET_HU:
            from .universe.hu_universe import hu_universe_name_map
            return hu_universe_name_map()
        if market == MARKET_CA:
            name_fallback = ca_universe_name_map()
            if not name_fallback:
                # Cold cache: try one refresh so board/name backfill works on
                # first add without a manual universe warm-up.
                try:
                    refresh_ca_universe()
                except CaUniverseError:
                    pass
                except Exception:
                    logging.getLogger(__name__).warning(
                        "ca_universe refresh skipped on add-company",
                        exc_info=True,
                    )
                name_fallback = ca_universe_name_map() or None
            return name_fallback
        return None

    def _with_global_reference_fallback(
        self,
        market: str,
        name_fallback: Optional[Mapping[str, Mapping[str, str]]],
    ) -> Optional[Mapping[str, Mapping[str, str]]]:
        """Merge Phase 1 global equity reference entries below the official map.

        Official universe fields always win (same ticker keeps the official
        entry). The third-party reference only backfills tickers the official
        universe does not know — today that is mostly ETF candidates for
        Euronext markets while the EODHD key is configured.
        """
        env_cache_path = os.environ.get(
            "GLOBAL_EQUITY_REFERENCE_CACHE_PATH"
        )
        cache_path = (
            Path(env_cache_path)
            if env_cache_path
            else Path(self.project_root) / GLOBAL_EQUITY_REFERENCE_CACHE_PATH
        )
        try:
            items = search_global_equity_reference(
                "", market=market, path=cache_path
            )
        except Exception:  # noqa: BLE001 - 参考层损坏不阻断添加
            LOGGER.warning(
                "global_equity_reference lookup failed for market=%s",
                market,
                exc_info=True,
            )
            return name_fallback
        if not items:
            return name_fallback
        merged = dict(name_fallback or {})
        for item in items:
            symbol = str(item.get("symbol") or "").strip()
            normalized = self._normalize_global_reference_symbol(
                market, symbol
            )
            if not normalized or normalized in merged:
                continue
            board = str(item.get("board") or item.get("exchange") or "")
            merged[normalized] = {
                "name": str(item.get("name") or normalized),
                "exchange": board,
                "board": board,
                "isin": str(item.get("isin") or ""),
                "instrument_type": str(item.get("instrument_type") or ""),
            }
        return merged or None

    @staticmethod
    def _normalize_global_reference_symbol(market: str, symbol: str) -> str:
        """Normalize a third-party symbol the same way add-company normalizes it."""
        if market == MARKET_BE:
            return normalize_be_ticker(symbol)
        if market == MARKET_DE:
            return normalize_de_ticker(symbol)
        if market == MARKET_FR:
            return normalize_fr_ticker(symbol)
        if market == MARKET_IT:
            return normalize_it_ticker(symbol)
        if market == MARKET_NL:
            return normalize_nl_ticker(symbol)
        return str(symbol or "").strip().upper()

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
        selected_date = date.fromisoformat(selected_text) if selected_text else datetime.now(EASTERN).date()
        lists = [dict(record) for record in self.repository.fixed_lists()]
        companies = self.repository.companies()
        counts = self.repository.counts(selected_date)
        for list_record in lists:
            slug = str(list_record["slug"])
            list_record["company_count"] = sum(slug in company["list_slugs"] for company in companies)
            list_record["unread_count"] = counts["list_unread"].get(slug, 0)
        return {
            "selected_date": selected_date.isoformat(),
            "report_selected_date": _shanghai_default_day(self._clock()).isoformat(),
            "display_date": f"{selected_date.strftime('%b')} {selected_date.day}, {selected_date.year}",
            "timezone": "America/New_York",
            "timezone_label": "ET",
            "lists": lists,
            "companies": companies,
            "counts": counts,
            "sources": self.repository.source_statuses(),
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

    def _daily(self, query: Mapping[str, Sequence[str]]) -> Mapping[str, Any]:
        selected_date = _query_date(query, "date") or _shanghai_default_day(self._clock())
        list_slug = _first(query, "list")
        return self._daily_range_payload(selected_date, selected_date, list_slug)["days"][0]

    def _daily_range(self, query: Mapping[str, Sequence[str]]) -> Mapping[str, Any]:
        today = _shanghai_default_day(self._clock())
        requested_start = _query_date(query, "start_date")
        requested_end = _query_date(query, "end_date")
        # An end date on its own is a request for that one report.  Defaulting
        # the omitted start to today would turn a valid historic request into
        # an inverted range.
        end_date = requested_end or requested_start or today
        start_date = requested_start or end_date
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        return self._daily_range_payload(
            start_date,
            end_date,
            _first(query, "list"),
        )

    def _research_scope(
        self,
        requested_start: Optional[date],
        requested_end: Optional[date],
        list_slug: Optional[str],
    ) -> ResearchScope:
        """Resolve a Research scope with the exact Daily range semantics.

        Defaults mirror ``/api/daily-range``: an omitted end falls back to the
        requested start and then to the current Asia/Shanghai day; an omitted
        start falls back to the end. ``start > end`` is a hard 400 upstream.
        """
        today = _shanghai_default_day(self._clock())
        end_date = requested_end or requested_start or today
        start_date = requested_start or end_date
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        return ResearchScope(
            start_date=start_date,
            end_date=end_date,
            list_scope=list_slug,
        )

    def _daily_range_payload(
        self,
        start_date: date,
        end_date: date,
        list_slug: Optional[str],
    ) -> Mapping[str, Any]:
        # Filter the report categories in SQL, then annotate the complete
        # range once so soft-dedupe can see pairs split across DB pages.
        # This is the same shared query boundary Research consumes, so the
        # Daily display rows and the Research evidence set are identical.
        feed_result = self.repository.daily_display_rows(
            list_slug, start_date, end_date
        )
        items = feed_result.items
        day_count = (end_date - start_date).days + 1
        performance = _daily_range_performance(
            day_count=day_count,
            query_ms=feed_result.query_ms,
            pages_fetched=feed_result.pages_fetched,
        )
        day_payloads: Dict[date, Dict[str, Any]] = {}
        cursor = start_date
        while cursor <= end_date:
            day_payloads[cursor] = {
                "date": cursor.isoformat(),
                "timezone": "Asia/Shanghai",
                "list": list_slug,
                "companies": [],
                "item_count": 0,
                "company_count": 0,
                "counts": {"filings": 0, "news": 0, "community": 0},
            }
            cursor += timedelta(days=1)

        groups: Dict[date, Dict[str, Dict[str, Any]]] = {
            day: {} for day in day_payloads
        }
        for item in items:
            category = _daily_item_category(str(item["source_type"]))
            if category is None:
                continue
            item_date = _daily_item_date(item)
            if item_date not in groups:
                continue
            key = f"{item['ticker']}:{item['market']}"
            group = groups[item_date].setdefault(key, {
                "ticker": item["ticker"],
                "name": item["company_name"],
                "exchange": item["exchange"],
                "market": item["market"],
                "items": [],
            })
            also_seen = item.get("also_seen_on_labels") or item.get("also_from_labels") or ()
            group["items"].append({
                "time": item["effective_at"],
                "type": _daily_item_type(str(item["source_type"])),
                "source": _daily_source_label(item),
                "title": item["title"],
                "url": item["url"],
                "also_seen_on": list(also_seen),
                "_category": category,
                "_sort_dt": _daily_effective_at(item["effective_at"]),
                "_external_id": str(item["external_id"]),
                "_id": int(item["id"]),
            })
            day_payloads[item_date]["item_count"] += 1
            day_payloads[item_date]["counts"][category] += 1

        for day, company_groups in groups.items():
            for group in company_groups.values():
                group["items"].sort(key=_daily_item_sort_key)
                for entry in group["items"]:
                    entry.pop("_category", None)
                    entry.pop("_sort_dt", None)
                    entry.pop("_external_id", None)
                    entry.pop("_id", None)
            day_payloads[day]["companies"] = sorted(
                company_groups.values(),
                key=_daily_company_sort_key,
            )
            day_payloads[day]["company_count"] = len(day_payloads[day]["companies"])

        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "timezone": "Asia/Shanghai",
            "list": list_slug,
            "days": [day_payloads[day] for day in sorted(day_payloads, reverse=True)],
            "item_count": sum(
                int(payload["item_count"]) for payload in day_payloads.values()
            ),
            "performance": performance,
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
        response = self.application.handle(
            self.command, self.path, body, headers=self.headers
        )
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
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
        # Graceful shutdown: wait for any in-flight model generation to finish
        # so a card is not left stuck in "generating" and no model request keeps
        # running after the server has gone away.
        application.research.shutdown()
        server.server_close()


def _decode_json(body: bytes) -> Mapping[str, Any]:
    payload = json.loads(body.decode("utf-8") or "{}")
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


_MARKET_ALIASES = {
    "usa": "us", "united states": "us",
    "japan": "jp",
    "hong kong": "hk",
    "china": "cn",
    "korea": "kr", "south korea": "kr",
    "gb": "uk", "united kingdom": "uk",
    "taiwan": "tw",
    "canada": "ca",
    "australia": "au",
    "belgium": "be",
    "france": "fr",
    "germany": "de",
    "netherlands": "nl",
    "italy": "it",
    "spain": "es",
    "singapore": "sg",
    "switzerland": "ch",
    "poland": "pl",
    "sweden": "se",
    "aqse": "aq", "aquis": "aq",
    "cboe europe": "cxe",
    "european mutual funds": "emf",
    "turquoise": "trq",
    "eurex": "eux",
}


def _parse_company_csv(
    raw_csv: str,
    lists: Sequence[Mapping[str, Any]],
) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
    """Parse ticker/market/list CSV or spreadsheet rows with partial errors."""
    text = raw_csv.lstrip("\ufeff").strip()
    if not text:
        raise ValueError("Paste CSV data or choose a CSV file")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        raise ValueError("CSV must include a header row")
    if len(rows) > 501:
        raise ValueError("CSV can contain at most 500 data rows")

    header_aliases = {
        "ticker": "ticker", "symbol": "ticker", "code": "ticker",
        "market": "market", "region": "market",
        "list": "list", "list_type": "list", "list name": "list",
    }
    header = [
        header_aliases.get(cell.strip().lower(), cell.strip().lower())
        for cell in rows[0]
    ]
    missing = [name for name in ("ticker", "market", "list") if name not in header]
    if missing:
        raise ValueError(
            "CSV header must contain ticker, market, list; missing: "
            + ", ".join(missing)
        )
    indexes = {name: header.index(name) for name in ("ticker", "market", "list")}
    max_index = max(indexes.values())
    list_aliases: Dict[str, str] = {}
    for record in lists:
        slug = str(record["slug"])
        list_aliases[slug.casefold()] = slug
        list_aliases[str(record["name"]).casefold()] = slug

    aggregated: Dict[Tuple[str, str], Dict[str, Any]] = {}
    failures: List[Mapping[str, Any]] = []
    for row_number, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        padded = row + [""] * max(0, max_index + 1 - len(row))
        ticker = padded[indexes["ticker"]].strip().upper()
        raw_market = padded[indexes["market"]].strip().casefold()
        market = _MARKET_ALIASES.get(raw_market, raw_market)
        raw_list = padded[indexes["list"]].strip()
        list_slug = list_aliases.get(raw_list.casefold(), "")
        error = ""
        if not ticker:
            error = "Ticker is required."
        elif not all(character.isalnum() or character in ".-_" for character in ticker):
            error = "Ticker may contain only letters, numbers, dot, hyphen, or underscore."
        elif len(ticker) > 32:
            error = "Ticker must be 32 characters or fewer."
        elif not raw_market:
            error = "Market is required."
        elif market not in ALLOWED_MARKETS:
            error = "Market must be one of: " + ", ".join(sorted(ALLOWED_MARKETS)) + "."
        elif not raw_list:
            error = "List is required."
        elif not list_slug:
            error = "List was not found. Use an existing list slug or name."
        if error:
            failures.append({
                "row": row_number,
                "ticker": ticker or "—",
                "error": error,
            })
            continue

        key = (ticker, market)
        entry = aggregated.setdefault(key, {
            "row": row_number,
            "ticker": ticker,
            "market": market,
            "lists": [],
        })
        if list_slug not in entry["lists"]:
            entry["lists"].append(list_slug)

    if not aggregated and not failures:
        raise ValueError("CSV must include at least one data row")
    return list(aggregated.values()), failures


_CSRF_REJECTED = "research_csrf_rejected"


def _header_value(headers: Mapping[str, Any], name: str) -> str:
    value = headers.get(name)
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _effective_port(parsed_url: Any, scheme: str) -> int:
    """Return the port after applying the http/https default-port rule."""
    if parsed_url.port is not None:
        return int(parsed_url.port)
    return 443 if scheme == "https" else 80


def _expected_scheme() -> str:
    """Return the externally-visible scheme, defaulting to http.

    The scheme of the reverse-proxy entry point is explicitly configured via
    ``WEB_EXTERNAL_SCHEME``; client-supplied ``X-Forwarded-Proto`` is never
    trusted because the app cannot reliably tell a trusted proxy request from
    a direct request.
    """
    value = os.environ.get("WEB_EXTERNAL_SCHEME", "http").strip().lower()
    return value if value in {"http", "https"} else "http"


def _same_origin_json_write_rejection(
    headers: Mapping[str, Any],
) -> Optional[WebResponse]:
    """Reject a JSON POST that is not a same-origin, structured request.

    A write endpoint with side effects (which may trigger paid model calls or
    evidence exfiltration) must carry an ``application/json`` Content-Type and
    an Origin (or, when absent, a Referer) whose scheme, hostname, and
    effective port all match the request Host. Host/Origin/Referer are parsed
    as URLs; no ``startswith`` guessing.
    """
    content_type = _header_value(headers, "Content-Type").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _csrf_rejection("Content-Type must be application/json")

    host = _header_value(headers, "Host")
    parsed_host = urlparse("//" + host) if host else urlparse("//")
    host_hostname = (parsed_host.hostname or "").lower()
    if not host_hostname:
        return _csrf_rejection("missing Host header")
    scheme = _expected_scheme()
    host_port = _effective_port(parsed_host, scheme)

    origin = _header_value(headers, "Origin")
    referer = _header_value(headers, "Referer")
    if origin:
        return _validate_origin_value(origin, scheme, host_hostname, host_port)
    if referer:
        return _validate_origin_value(referer, scheme, host_hostname, host_port)
    return _csrf_rejection("missing Origin and Referer headers")


def _validate_origin_value(
    value: str,
    scheme: str,
    host_hostname: str,
    host_port: int,
) -> Optional[WebResponse]:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return _csrf_rejection("origin must use http or https")
    origin_hostname = (parsed.hostname or "").lower()
    if not origin_hostname:
        return _csrf_rejection("origin has no hostname")
    if parsed.scheme != scheme:
        return _csrf_rejection("cross-origin request rejected")
    if origin_hostname != host_hostname:
        return _csrf_rejection("cross-origin request rejected")
    if _effective_port(parsed, parsed.scheme) != host_port:
        return _csrf_rejection("cross-origin request rejected")
    return None


def _csrf_rejection(message: str) -> WebResponse:
    return WebResponse(
        403,
        json.dumps({"error": message, "code": _CSRF_REJECTED}).encode("utf-8"),
    )
_MARKET_ALIASES = {
    "usa": "us", "united states": "us",
    "japan": "jp",
    "hong kong": "hk",
    "china": "cn",
    "korea": "kr", "south korea": "kr",
    "gb": "uk", "united kingdom": "uk",
    "taiwan": "tw",
    "canada": "ca",
    "australia": "au",
    "belgium": "be",
    "france": "fr",
    "germany": "de",
    "netherlands": "nl",
    "italy": "it",
    "spain": "es",
    "singapore": "sg",
    "switzerland": "ch",
    "poland": "pl",
    "sweden": "se",
    "aqse": "aq", "aquis": "aq",
    "cboe europe": "cxe",
    "european mutual funds": "emf",
    "turquoise": "trq",
    "eurex": "eux",
}


def _parse_company_csv(
    raw_csv: str,
    lists: Sequence[Mapping[str, Any]],
) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
    """Parse ticker/market/list CSV or spreadsheet rows with partial errors."""
    text = raw_csv.lstrip("\ufeff").strip()
    if not text:
        raise ValueError("Paste CSV data or choose a CSV file")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    if not rows:
        raise ValueError("CSV must include a header row")
    if len(rows) > 501:
        raise ValueError("CSV can contain at most 500 data rows")

    header_aliases = {
        "ticker": "ticker", "symbol": "ticker", "code": "ticker",
        "market": "market", "region": "market",
        "list": "list", "list_type": "list", "list name": "list",
    }
    header = [
        header_aliases.get(cell.strip().lower(), cell.strip().lower())
        for cell in rows[0]
    ]
    missing = [name for name in ("ticker", "market", "list") if name not in header]
    if missing:
        raise ValueError(
            "CSV header must contain ticker, market, list; missing: "
            + ", ".join(missing)
        )
    indexes = {name: header.index(name) for name in ("ticker", "market", "list")}
    max_index = max(indexes.values())
    list_aliases: Dict[str, str] = {}
    for record in lists:
        slug = str(record["slug"])
        list_aliases[slug.casefold()] = slug
        list_aliases[str(record["name"]).casefold()] = slug

    aggregated: Dict[Tuple[str, str], Dict[str, Any]] = {}
    failures: List[Mapping[str, Any]] = []
    for row_number, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        padded = row + [""] * max(0, max_index + 1 - len(row))
        ticker = padded[indexes["ticker"]].strip().upper()
        raw_market = padded[indexes["market"]].strip().casefold()
        market = _MARKET_ALIASES.get(raw_market, raw_market)
        raw_list = padded[indexes["list"]].strip()
        list_slug = list_aliases.get(raw_list.casefold(), "")
        error = ""
        if not ticker:
            error = "Ticker is required."
        elif not all(character.isalnum() or character in ".-_" for character in ticker):
            error = "Ticker may contain only letters, numbers, dot, hyphen, or underscore."
        elif len(ticker) > 32:
            error = "Ticker must be 32 characters or fewer."
        elif not raw_market:
            error = "Market is required."
        elif market not in ALLOWED_MARKETS:
            error = "Market must be one of: " + ", ".join(sorted(ALLOWED_MARKETS)) + "."
        elif not raw_list:
            error = "List is required."
        elif not list_slug:
            error = "List was not found. Use an existing list slug or name."
        if error:
            failures.append({
                "row": row_number,
                "ticker": ticker or "—",
                "error": error,
            })
            continue

        key = (ticker, market)
        entry = aggregated.setdefault(key, {
            "row": row_number,
            "ticker": ticker,
            "market": market,
            "lists": [],
        })
        if list_slug not in entry["lists"]:
            entry["lists"].append(list_slug)

    if not aggregated and not failures:
        raise ValueError("CSV must include at least one data row")
    return list(aggregated.values()), failures


def _first(query: Mapping[str, Sequence[str]], key: str) -> Optional[str]:
    values = query.get(key)
    return values[-1] if values else None


def _query_date(query: Mapping[str, Sequence[str]], key: str) -> Optional[date]:
    value = _first(query, key)
    return date.fromisoformat(value) if value else None


def _payload_date(payload: Mapping[str, Any], key: str) -> Optional[date]:
    """Parse an optional ISO date from a JSON body; invalid values raise."""
    value = payload.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be an ISO date string")
    return date.fromisoformat(value.strip())


def _shanghai_default_day(now: Optional[datetime] = None) -> date:
    """Return the current Asia/Shanghai calendar day for Daily Report defaults.

    ``now`` may be injected as a fixed instant so tests do not have to
    monkeypatch the clock.  A naive ``now`` is treated as UTC, matching the
    service's canonical timestamps.  This is intentionally distinct from the
    Eastern ``selected_date`` still used by Today, badges, counts and the
    scheduler.
    """
    current = now if now is not None else datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(SHANGHAI).date()


def _required_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a JSON boolean")
    return value


def _optional_bool(payload: Mapping[str, Any], key: str, default: bool) -> bool:
    """Return a strict JSON boolean, or ``default`` when the key is absent.

    A string like ``"false"``, a number, an array, an object, or ``null`` is
    rejected instead of being coerced by ``bool()``.
    """
    if key not in payload:
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a JSON boolean")
    return value


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
    )


def _filter_dict(filters: FeedFilters) -> Mapping[str, Any]:
    return {
        "list": filters.list_slug,
        "ticker": filters.ticker,
        "type": filters.information_type,
        "form": filters.form_type,
        "start_date": filters.start_date.isoformat() if filters.start_date else None,
        "end_date": filters.end_date.isoformat() if filters.end_date else None,
        "read": filters.read_state,
        "amendment": filters.amendment,
        "q": filters.query,
        "page": filters.page,
        "page_size": filters.page_size,
    }


def _view_for_path(path: str) -> str:
    if path in {"/", "/today", "/information", "/search"}:
        return "today"
    if path == "/research":
        return "research"
    if path in {"/manage", "/activity", "/sources", "/settings"} or path.startswith("/lists/"):
        return "manage"
    return path.rsplit("/", 1)[-1]


def _fallback_language(value: Optional[str]) -> str:
    """Return a supported language, defaulting to ``en`` for read endpoints."""
    if not value:
        return "en"
    try:
        return validate_language(value)
    except ValueError:
        return "en"


def _trailing_id(path: str, prefix: str) -> int:
    segment = path[len(prefix):].split("/", 1)[0]
    return int(segment)


def _research_card_payload(
    card: Mapping[str, Any],
    company: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    content = None
    if card.get("content_json"):
        content = card_from_json(card["content_json"])
    evidence = list(card.get("evidence") or ())
    company = company or {}
    # Identity snapshot: cards written after the snapshot migration carry a
    # frozen company name/ticker/market on the row. Only legacy cards (all
    # three snapshot columns NULL) fall back to the current identity, purely
    # as a compatibility path. Newly generated cards never use this fallback,
    # and it never alters the evidence snapshot, scope, or generation time.
    company_name = card.get("company_name_snapshot")
    ticker = card.get("ticker_snapshot")
    market = card.get("market_snapshot")
    if company_name is None and ticker is None and market is None:
        company_name = company.get("name")
        ticker = company.get("ticker")
        market = company.get("market")
    return {
        "id": int(card["id"]),
        "company_id": int(card["company_id"]),
        "company_name": company_name,
        "ticker": ticker,
        "market": market,
        "language": card["language"],
        "status": card["status"],
        "generated_at": card["generated_at"],
        "error_code": card["error_code"],
        "start_date": card.get("start_date"),
        "end_date": card.get("end_date"),
        "list_scope": card.get("list_scope"),
        "evidence_total": len(evidence),
        "evidence_sent": len(evidence),
        "filing_count": sum(
            1 for item in evidence if item.get("information_type") == "filing"
        ),
        "news_count": sum(
            1 for item in evidence if item.get("information_type") == "news"
        ),
        "community_count": sum(
            1 for item in evidence if item.get("information_type") == "community"
        ),
        "content": content,
        "evidence": evidence,
    }


def _daily_item_type(source_type: str) -> str:
    if source_type in {"regulatory_filing", "regulatory_disclosure"}:
        return "Filing"
    if source_type == "news":
        return "News"
    if source_type == "community":
        return "Community"
    return source_type.replace("_", " ").title()


def _daily_source_label(item: Mapping[str, Any]) -> str:
    metadata = item.get("raw_metadata") or {}
    if item.get("source_type") == "news" and isinstance(metadata, dict):
        publisher = str(metadata.get("source") or "").strip()
        if publisher:
            return publisher
    return str(item.get("source_label") or item.get("source") or "Unavailable")


_DAILY_CATEGORY_ORDER = {"filings": 0, "news": 1, "community": 2}


def _daily_item_category(source_type: str) -> Optional[str]:
    if source_type in {"regulatory_filing", "regulatory_disclosure"}:
        return "filings"
    if source_type == "news":
        return "news"
    if source_type == "community":
        return "community"
    return None


def _daily_effective_at(value: Any) -> datetime:
    """Parse a feed timestamp using the same UTC assumption as stored items.

    Historical rows predating ``effective_at`` can contain a naive ISO value.
    Treating it as UTC keeps the Shanghai report day independent of where the
    service happens to run.
    """
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _daily_item_date(item: Mapping[str, Any]) -> date:
    """Return the report day in Asia/Shanghai, preserving date-only disclosures.

    Date-only disclosures (e.g. TWSE/TPEx material, BME relevant facts) carry
    ``raw_metadata.calendar_date`` and must be placed on that calendar day
    without a timezone conversion.  Everything else uses the canonical event
    time already resolved by the repository (``effective_at``), converted to
    Asia/Shanghai.  Collection time is never consulted.
    """
    metadata = item.get("raw_metadata")
    if isinstance(metadata, Mapping):
        calendar_date = metadata.get("calendar_date")
        if isinstance(calendar_date, str):
            try:
                return date.fromisoformat(calendar_date)
            except ValueError:
                pass
    return _daily_effective_at(item["effective_at"]).astimezone(SHANGHAI).date()


def _daily_item_sort_key(item: Mapping[str, Any]) -> Tuple[Any, ...]:
    """Category order first, then event time descending, then stable tiebreakers."""
    return (
        _DAILY_CATEGORY_ORDER[item["_category"]],
        -item["_sort_dt"].timestamp(),
        item["_external_id"],
        item["_id"],
    )


def _daily_company_sort_key(group: Mapping[str, Any]) -> Tuple[str, str, str]:
    """Canonical Daily Report company order: name, ticker, market."""
    return (
        str(group["name"]).casefold(),
        str(group["ticker"]),
        str(group["market"]),
    )


def _daily_range_warn_days() -> int:
    return _environment_int("DAILY_RANGE_WARN_DAYS", 90, minimum=1, maximum=366)


def _daily_range_slow_ms() -> int:
    return _environment_int("DAILY_RANGE_SLOW_MS", 3000, minimum=0, maximum=120_000)


def _daily_range_performance(
    *,
    day_count: int,
    query_ms: int,
    pages_fetched: int,
) -> Mapping[str, Any]:
    warn_days = _daily_range_warn_days()
    slow_ms = _daily_range_slow_ms()
    warnings: List[str] = []
    if day_count >= warn_days:
        warnings.append(
            f"Large date range ({day_count} days). "
            "Daily reports load the full filtered result set; "
            "consider a shorter range for faster loads."
        )
    if query_ms >= slow_ms:
        warnings.append(
            f"Slow query ({query_ms} ms). "
            "Consider narrowing the date range or list filter."
        )
    if warnings:
        LOGGER.warning(
            "daily-range performance: days=%s query_ms=%s pages=%s warnings=%s",
            day_count,
            query_ms,
            pages_fetched,
            warnings,
        )
    return {
        "day_count": day_count,
        "query_ms": query_ms,
        "pages_fetched": pages_fetched,
        "warn_days": warn_days,
        "slow_ms": slow_ms,
        "warnings": warnings,
    }


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
    start_dates = [
        str(summary["start_date"])
        for summary in summaries
        if summary["start_date"] is not None
    ]
    end_dates = [
        str(summary["end_date"])
        for summary in summaries
        if summary["end_date"] is not None
    ]
    return {
        "status": status,
        "tickers": [
            ticker for summary in summaries for ticker in summary["tickers"]
        ],
        "start_date": min(start_dates) if start_dates else None,
        "end_date": max(end_dates) if end_dates else None,
        "records_fetched": sum(int(summary["records_fetched"]) for summary in summaries),
        "inserted": sum(int(summary["inserted"]) for summary in summaries),
        "updated": sum(int(summary["updated"]) for summary in summaries),
        "failures": [
            failure for summary in summaries for failure in summary["failures"]
        ],
    }


if __name__ == "__main__":
    main()
