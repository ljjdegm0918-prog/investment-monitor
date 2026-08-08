"""Resolve web-list companies through the official SEC ticker mapping."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Mapping, Optional

from .client import SECClient
from .connector import TickerCIKResolver, _read_cache_ttl


class SECCompanyResolver:
    """Use the local SEC cache first and refresh through the SEC client if needed."""

    def __init__(
        self,
        cache_path: Path,
        live_resolver: Optional[TickerCIKResolver] = None,
    ) -> None:
        self._cache_path = cache_path
        self._live_resolver = live_resolver

    @classmethod
    def from_environment(cls, cache_path: Path) -> "SECCompanyResolver":
        client = SECClient.from_environment()
        return cls(
            cache_path,
            TickerCIKResolver(
                client=client,
                cache_path=cache_path,
                cache_ttl_seconds=_read_cache_ttl(),
            ),
        )

    def resolve(self, ticker: str) -> Optional[Mapping[str, str]]:
        normalized = ticker.strip().upper()
        cached = self._find_cached(normalized)
        if cached is not None:
            return cached
        if self._live_resolver is None:
            return None
        try:
            cik, name = self._live_resolver.resolve(normalized)
        except Exception:
            return None
        return self._identity(normalized, cik, name)

    def search(self, query: str, *, limit: int = 20) -> List[Mapping[str, str]]:
        """Search the local official SEC mapping without making a live request."""
        term = query.strip().casefold()
        if not term:
            return []
        try:
            payload: Any = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, dict):
            return []
        matches = []
        for record in payload.values():
            if not isinstance(record, dict):
                continue
            ticker = str(record.get("ticker") or "").strip().upper()
            name = str(record.get("title") or ticker).strip()
            if term not in ticker.casefold() and term not in name.casefold():
                continue
            try:
                cik = int(record["cik_str"])
            except (KeyError, TypeError, ValueError):
                continue
            matches.append({
                **self._identity(ticker, cik, name),
                "market": "us",
                "region": "United States",
            })
        matches.sort(key=lambda item: (
            0 if item["ticker"].casefold() == term else 1,
            0 if item["name"].casefold().startswith(term) else 1,
            item["ticker"],
        ))
        return matches[:max(1, min(limit, 50))]

    def _find_cached(self, ticker: str) -> Optional[Mapping[str, str]]:
        try:
            payload: Any = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        for record in payload.values():
            if not isinstance(record, dict) or str(record.get("ticker", "")).upper() != ticker:
                continue
            try:
                cik = int(record["cik_str"])
            except (KeyError, TypeError, ValueError):
                return None
            return self._identity(ticker, cik, str(record.get("title") or ticker))
        return None

    @staticmethod
    def _identity(ticker: str, cik: int, name: str) -> Mapping[str, str]:
        return {
            "ticker": ticker,
            "name": name,
            "cik": str(cik).zfill(10),
            "exchange": "Unavailable",
            "mapping_status": "mapped",
        }
