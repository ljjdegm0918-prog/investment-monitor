"""Canonical raw-record provenance for official regulatory disclosures."""

from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import json
from typing import Any, Mapping, Optional


def json_safe_snapshot(value: Any) -> Any:
    """Return a deterministic JSON-safe copy without inventing field values."""
    if isinstance(value, Mapping):
        return {
            str(key): json_safe_snapshot(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [json_safe_snapshot(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def build_raw_provenance(
    *,
    official_source_id: Optional[str],
    official_source_url: Optional[str],
    retrieval_url: Optional[str],
    raw_payload: Any,
    raw_payload_format: str,
    classification_code: Optional[str],
    classification_label: Optional[str],
    published_at_raw: Optional[str],
    published_timezone: str,
    revision_semantics: str = "unknown",
) -> Mapping[str, Any]:
    """Build the v1 provenance envelope and hash the canonical raw record."""
    snapshot = json_safe_snapshot(raw_payload)
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "provenance_schema_version": 1,
        "official_source_id": _optional_text(official_source_id),
        "official_source_url": _optional_text(official_source_url),
        "retrieval_url": _optional_text(retrieval_url),
        "raw_payload": snapshot,
        "raw_payload_format": str(raw_payload_format),
        "raw_content_hash": sha256(canonical.encode("utf-8")).hexdigest(),
        "raw_classification": {
            "code": _optional_text(classification_code),
            "label": _optional_text(classification_label),
        },
        "published_at_raw": _optional_text(published_at_raw),
        "published_timezone": str(published_timezone or "unknown"),
        "revision_semantics": str(revision_semantics or "unknown"),
    }


def _optional_text(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    return text or None
