"""OpenDART company master (corpCode.xml) cache."""

from __future__ import annotations

import io
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import zipfile
import xml.etree.ElementTree as ElementTree

from .client import DartClient, DartDataError, DartError, DartRequestError

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60


class CorpCodeCache:
    """Resolve KR stock codes to OpenDART corp codes with a local cache."""

    def __init__(
        self,
        client: Optional[DartClient],
        cache_path: Path,
        ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        clock: Any = time.time,
    ) -> None:
        self._client = client
        self._cache_path = Path(cache_path)
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._mapping: Optional[Dict[str, Tuple[str, str]]] = None

    def resolve(self, ticker: str) -> Optional[Tuple[str, str, str]]:
        """Return (corp_code, corp_name, normalized_ticker) or None."""
        raw = ticker.strip()
        if raw.isdigit():
            key = raw.zfill(6)
        else:
            key = raw.upper()
        mapping = self._load_mapping()
        entry = mapping.get(key)
        if entry is None:
            return None
        corp_code, corp_name = entry
        return corp_code, corp_name, key

    def all_entries(self) -> Dict[str, Tuple[str, str]]:
        """Return all cached stock_code -> (corp_code, corp_name) pairs."""
        return dict(self._load_mapping())

    def _load_mapping(self) -> Dict[str, Tuple[str, str]]:
        if self._mapping is not None:
            return self._mapping
        cached_payload = self._read_cached_payload()
        if self._cache_is_fresh() and cached_payload is not None:
            try:
                self._mapping = self._parse_payload(cached_payload)
                return self._mapping
            except DartDataError:
                pass
        try:
            payload = self._download_and_cache()
        except DartError:
            if cached_payload is None:
                raise
            LOGGER.warning(
                "OpenDART corp code refresh failed; using stale cache: %s",
                self._cache_path,
            )
            payload = cached_payload
        self._mapping = self._parse_payload(payload)
        return self._mapping

    def _read_cached_payload(self) -> Optional[Any]:
        try:
            with self._cache_path.open("r", encoding="utf-8") as cache_file:
                return json.load(cache_file)
        except (OSError, json.JSONDecodeError):
            return None

    def _cache_is_fresh(self) -> bool:
        try:
            age = float(self._clock()) - self._cache_path.stat().st_mtime
        except OSError:
            return False
        return 0 <= age <= self._ttl_seconds

    def _download_and_cache(self) -> Dict[str, Tuple[str, str]]:
        if self._client is None:
            raise DartRequestError(
                "DART_API_KEY is not configured; cannot download corp codes."
            )
        data = self._client.get_bytes("corpCode.xml", {})
        mapping = self._parse_zip(data)
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._cache_path.with_suffix(
            self._cache_path.suffix + ".tmp"
        )
        try:
            with temporary_path.open("w", encoding="utf-8") as cache_file:
                json.dump(mapping, cache_file, ensure_ascii=False)
            temporary_path.replace(self._cache_path)
        except OSError as error:
            raise DartDataError(
                f"Could not write OpenDART corp code cache: "
                f"{self._cache_path}"
            ) from error
        return mapping

    @staticmethod
    def _parse_zip(data: bytes) -> Dict[str, Tuple[str, str]]:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                xml_bytes = archive.read("CORPCODE.xml")
        except (zipfile.BadZipFile, KeyError) as error:
            raise DartDataError(
                "OpenDART corpCode response is not a valid CORPCODE.xml zip."
            ) from error
        try:
            root = ElementTree.fromstring(xml_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ElementTree.ParseError) as error:
            raise DartDataError(
                "OpenDART corpCode.xml could not be parsed."
            ) from error

        mapping: Dict[str, Tuple[str, str]] = {}
        for item in root.findall("list"):
            stock_code = (item.findtext("stock_code") or "").strip()
            if not stock_code:
                continue
            corp_code = (item.findtext("corp_code") or "").strip()
            corp_name = (item.findtext("corp_name") or "").strip()
            key = (
                stock_code.zfill(6)
                if stock_code.isdigit()
                else stock_code
            )
            mapping[key] = (corp_code, corp_name)
        return mapping

    @staticmethod
    def _parse_payload(payload: Any) -> Dict[str, Tuple[str, str]]:
        if not isinstance(payload, dict):
            raise DartDataError(
                "OpenDART corp code cache must be a JSON object."
            )
        mapping: Dict[str, Tuple[str, str]] = {}
        for key, raw_value in payload.items():
            if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 2:
                raise DartDataError(
                    "OpenDART corp code cache entries must be [code, name]."
                )
            mapping[str(key)] = (str(raw_value[0]), str(raw_value[1]))
        return mapping
