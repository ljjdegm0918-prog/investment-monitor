"""Orchestration layer for the Research feature.

``ResearchService`` combines the web repository (company/evidence lookup), the
research repository (card persistence), the model adapter, and a single-worker
background executor. The web layer calls this service; the browser never
constructs a model request and never supplies evidence, prompt, base URL, model
or API key.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .research import (
    ERROR_DISABLED,
    ERROR_GENERATION_IN_PROGRESS,
    ERROR_INSUFFICIENT_EVIDENCE,
    ERROR_INTERNAL,
    ERROR_INVALID_MODEL_RESPONSE,
    ERROR_NO_ELIGIBLE_EVIDENCE,
    ERROR_NOT_CONFIGURED,
    ERROR_RANGE_TOO_LARGE,
    ResearchScope,
    ResearchSettings,
    EvidenceSelection,
    ResearchEvidence,
    build_system_prompt,
    build_user_prompt,
    card_to_json,
    evidence_ref_map,
    select_evidence,
    selectable_status,
    validate_language,
    validate_research_card,
)
from .research_ai import ResearchAIError, ResearchAIClient
from .research_repository import ResearchRepository

LOGGER = logging.getLogger(__name__)

# The only list scopes the Research page accepts. "all" is the union of the
# three fixed lists; a custom list is never a valid Research scope.
RESEARCH_LIST_SLUGS = ("all", "holdings", "planned", "watchlist")


def validate_list_slug(value: Optional[str]) -> Optional[str]:
    """Normalize a list query parameter to a valid Research scope.

    ``None`` and ``""`` become ``None`` (union). An unknown slug raises
    ``ValueError`` so the caller can return a 400.
    """
    if not value:
        return None
    slug = str(value).strip()
    if slug == "all":
        return None
    if slug not in RESEARCH_LIST_SLUGS:
        raise ValueError("list must be one of: all, holdings, planned, watchlist")
    return slug

_NEWS_ONLY_LIMITATION = {
    "en": "No official disclosure (filing) evidence is available; coverage is based on news reports only.",
    "zh-CN": "没有官方披露（申报）证据，覆盖情况仅基于新闻报道。",
}


class ResearchService:
    """Coordinates evidence selection, generation, and card persistence."""

    def __init__(
        self,
        web_repository: Any,
        database_path: Path,
        settings: Optional[ResearchSettings] = None,
        *,
        ai_client: Optional[ResearchAIClient] = None,
        synchronous: bool = False,
    ) -> None:
        self._web = web_repository
        self._repo = ResearchRepository(database_path)
        self._settings = settings if settings is not None else ResearchSettings.from_environment()
        self._ai = ai_client if ai_client is not None else ResearchAIClient(self._settings)
        self._synchronous = synchronous
        self._lock = threading.Lock()
        self._executor: Optional[ThreadPoolExecutor] = None
        if not synchronous:
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="research-generation",
            )

    def model_status(self) -> Mapping[str, Any]:
        return self._settings.public_status

    def companies(
        self,
        scope: ResearchScope,
        language: str,
    ) -> List[Mapping[str, Any]]:
        """Return every research-visible company with its card status.

        Only companies in Holdings / Planned / Watchlist are returned; a
        company with no list membership or only in a custom list never shows.
        Every count and status is computed from the exact Daily display rows
        of the requested scope — never from an independent lookback window.
        """
        language = validate_language(language)
        rows = self._web.research_companies(scope.list_scope)
        scoped_rows = self._scoped_rows(scope)
        result: List[Mapping[str, Any]] = []
        for company in rows:
            company_id = int(company["id"])
            selection = self._select(
                company_id, language, scope, rows=scoped_rows
            )
            latest = self._repo.latest_card(company_id, language, scope)
            generating = self._repo.has_in_progress(company_id, language, scope)
            status = selectable_status(
                settings=self._settings,
                selection=selection,
                latest_card=latest,
                generating=generating,
            )
            latest_completed = self._repo.latest_completed_card(
                company_id, language, scope
            )
            result.append(
                {
                    "id": company_id,
                    "name": company["name"],
                    "ticker": company["ticker"],
                    "market": company["market"],
                    "lists": company["list_slugs"],
                    "evidence_total": selection.total if selection else 0,
                    "filing_count": selection.filing_count if selection else 0,
                    "news_count": selection.news_count if selection else 0,
                    "community_count": selection.community_count if selection else 0,
                    "latest_evidence_at": (
                        selection.evidence[0].event_at.isoformat()
                        if selection and selection.evidence
                        else None
                    ),
                    "status": status,
                    "stale": status == "stale",
                    "latest_card_id": latest_completed["id"] if latest_completed else None,
                    "latest_generated_at": (
                        latest_completed["generated_at"] if latest_completed else None
                    ),
                }
            )
        return result

    def card(self, card_id: int) -> Optional[Mapping[str, Any]]:
        return self._repo.card_by_id(card_id)

    def generate(
        self,
        company_id: int,
        language: str,
        scope: ResearchScope,
        force: bool = False,
    ) -> Mapping[str, Any]:
        language = validate_language(language)
        identity = self._web.company_identity(company_id)
        if identity is None or not _company_in_scope(identity, scope):
            raise ValueError("Company is not in the selected Research scope")
        if not self._settings.enabled:
            return _error(ERROR_DISABLED, "Research generation is disabled.")
        if not self._settings.configured:
            return _error(ERROR_NOT_CONFIGURED, "The model API key is not configured.")

        with self._lock:
            if self._repo.has_in_progress(company_id, language, scope):
                return _error(
                    ERROR_GENERATION_IN_PROGRESS,
                    "A generation is already in progress for this company, language and range.",
                )
            selection = self._select(company_id, language, scope)
            eligibility = _eligibility_error(selection)
            if eligibility is not None:
                return eligibility
            assert selection is not None
            if selection.too_large:
                return _error(
                    ERROR_RANGE_TOO_LARGE,
                    f"The selected range has {selection.total} evidence items, "
                    "which is too many to send without omitting any. "
                    "Please choose a shorter date range.",
                )
            if not force:
                latest = self._repo.latest_completed_card(company_id, language, scope)
                if latest is not None and latest["evidence_fingerprint"] == selection.fingerprint:
                    return {
                        "status": "cached",
                        "card_id": int(latest["id"]),
                        "generation_id": None,
                        "generated_at": latest["generated_at"],
                    }
            card_id = self._repo.create_generation(
                company_id=company_id,
                language=language,
                evidence_fingerprint=selection.fingerprint,
                model_provider_fingerprint=self._settings.provider_identifier,
                model_name=self._settings.model,
                scope=scope,
            )
        if self._synchronous:
            self._run_generation(card_id, company_id, language, selection, scope)
            return self._generation_result(card_id)
        assert self._executor is not None
        self._executor.submit(
            self._run_generation, card_id, company_id, language, selection, scope
        )
        return {
            "status": "generating",
            "card_id": card_id,
            "generation_id": card_id,
            "generated_at": None,
        }

    def generation_status(self, generation_id: int) -> Optional[Mapping[str, Any]]:
        card = self._repo.card_by_id(generation_id)
        if card is None:
            return None
        return {
            "generation_id": generation_id,
            "card_id": generation_id,
            "status": card["status"],
            "error_code": card.get("error_code"),
            "generated_at": card.get("generated_at"),
        }

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)

    def _scoped_rows(
        self,
        scope: ResearchScope,
    ) -> Tuple[Mapping[int, Tuple[Mapping[str, Any], ...]], int]:
        """Fetch the shared Daily display rows once and group them by company.

        Returns ``({company_id: rows}, total)`` where ``rows`` are the exact
        display rows Daily shows for that company in this scope. Grouping keys
        on the joined company id, not the item's own market, so an
        ``unknown``-market item lands on the company Daily displays it under.
        """
        result = self._web.daily_display_rows(
            scope.list_scope, scope.start_date, scope.end_date
        )
        grouped: Dict[int, List[Mapping[str, Any]]] = {}
        for row in result.items:
            grouped.setdefault(int(row["company_id"]), []).append(row)
        return (
            {company_id: tuple(rows) for company_id, rows in grouped.items()},
            len(result.items),
        )

    def _select(
        self,
        company_id: int,
        language: str,
        scope: ResearchScope,
        *,
        rows: Optional[Tuple[Mapping[int, Tuple[Mapping[str, Any], ...]], int]] = None,
    ) -> Optional[EvidenceSelection]:
        identity = self._web.company_identity(company_id)
        if identity is None:
            return None
        if rows is None:
            rows = self._scoped_rows(scope)
        grouped, _total = rows
        items = grouped.get(company_id, ())
        if not items:
            return None
        return select_evidence(
            items,
            company_id=company_id,
            language=language,
            settings=self._settings,
            scope=scope,
            company_name=identity.get("name"),
            ticker=identity.get("ticker"),
            market=identity.get("market"),
        )

    def _run_generation(
        self,
        card_id: int,
        company_id: int,
        language: str,
        selection: EvidenceSelection,
        scope: ResearchScope,
    ) -> None:
        """Run one generation using the frozen evidence selection.

        The selection is frozen at click time in ``generate``; the worker never
        re-queries evidence, so the fingerprint, the prompt evidence, and the
        saved snapshot are always the same immutable set. It re-checks the
        scope membership right before calling the model and fails safely
        (without calling the model) if the company left the selected list.
        """
        try:
            if selection.too_large:
                self._repo.fail_generation(card_id, ERROR_RANGE_TOO_LARGE)
                return
            identity = self._web.company_identity(company_id)
            if identity is None or not _company_in_scope(identity, scope):
                self._repo.fail_generation(card_id, ERROR_NO_ELIGIBLE_EVIDENCE)
                return
            system_prompt = build_system_prompt(language)
            user_prompt = build_user_prompt(
                company_name=str(identity["name"]),
                ticker=str(identity["ticker"]),
                market=str(identity["market"]),
                language=language,
                evidence=selection.evidence,
                news_only=selection.news_only,
            )
            raw = self._ai.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                language=language,
            )
            card = validate_research_card(
                raw,
                language=language,
                allowed_refs=evidence_ref_map(selection.evidence),
            )
            if selection.news_only:
                card = _mark_news_only(card, language)
            self._repo.complete_generation(
                card_id,
                company_id=company_id,
                content_json=card_to_json(card),
                evidence=selection.evidence,
            )
        except ResearchAIError as error:
            self._repo.fail_generation(card_id, error.code)
        except (ValueError, TypeError) as error:
            LOGGER.warning("Invalid model response for card %s: %s", card_id, error)
            self._repo.fail_generation(card_id, ERROR_INVALID_MODEL_RESPONSE)
        except Exception:
            LOGGER.exception("Research generation failed for card %s", card_id)
            self._repo.fail_generation(card_id, ERROR_INTERNAL)

    def _generation_result(self, card_id: int) -> Mapping[str, Any]:
        status = self.generation_status(card_id)
        if status is None:
            return {"status": "failed", "card_id": card_id, "generation_id": None, "generated_at": None}
        result = dict(status)
        result["generation_id"] = result.pop("generation_id", card_id)
        return result


def _error(code: str, message: str) -> Mapping[str, Any]:
    return {"status": "error", "code": code, "error": message, "card_id": None, "generation_id": None, "generated_at": None}


_FIXED_LIST_SLUGS = frozenset({"holdings", "planned", "watchlist"})


def _company_in_scope(identity: Mapping[str, Any], scope: ResearchScope) -> bool:
    """True when the company belongs to the selected Research list scope."""
    lists = set(identity.get("list_slugs") or ())
    if scope.list_scope is not None:
        return scope.list_scope in lists
    return bool(lists & _FIXED_LIST_SLUGS)


def _eligibility_error(
    selection: Optional[EvidenceSelection],
) -> Optional[Mapping[str, Any]]:
    if selection is None or selection.total == 0:
        return _error(ERROR_NO_ELIGIBLE_EVIDENCE, "No eligible evidence for this company.")
    if not selection.eligible:
        return _error(ERROR_INSUFFICIENT_EVIDENCE, "Insufficient evidence for this company.")
    return None


def _mark_news_only(card: Mapping[str, Any], language: str) -> Mapping[str, Any]:
    """Inject an application-fixed coverage note when only news exists.

    This is not model content: it is a fixed string appended by the app so the
    card always discloses the lack of official filing coverage.
    """
    updated = dict(card)
    coverage = dict(updated["coverage"])
    coverage["limitations"] = list(coverage["limitations"]) + [
        _NEWS_ONLY_LIMITATION.get(language, _NEWS_ONLY_LIMITATION["en"])
    ]
    updated["coverage"] = coverage
    return updated
