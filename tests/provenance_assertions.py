"""Shared assertions for the versioned official-source provenance contract."""

import hashlib
import json


def canonical_payload_hash(payload) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assert_official_provenance(
    testcase,
    item,
    *,
    expected_payload,
    official_source_id,
    official_source_url,
    retrieval_url,
    raw_payload_format,
    classification_code,
    classification_label,
    published_at_raw,
    published_timezone,
    revision_semantics="unknown",
) -> None:
    metadata = item.raw_metadata
    testcase.assertEqual(metadata["provenance_schema_version"], 1)
    testcase.assertEqual(metadata["official_source_id"], official_source_id)
    testcase.assertEqual(metadata["official_source_url"], official_source_url)
    testcase.assertEqual(metadata["retrieval_url"], retrieval_url)
    testcase.assertEqual(metadata["raw_payload"], expected_payload)
    # The payload must remain safe to encode as JSON after normalization.
    json.dumps(metadata["raw_payload"], ensure_ascii=False)
    testcase.assertEqual(metadata["raw_payload_format"], raw_payload_format)
    testcase.assertEqual(
        metadata["raw_content_hash"],
        canonical_payload_hash(expected_payload),
    )
    testcase.assertEqual(
        metadata["raw_classification"],
        {"code": classification_code, "label": classification_label},
    )
    testcase.assertEqual(metadata["published_at_raw"], published_at_raw)
    testcase.assertEqual(metadata["published_timezone"], published_timezone)
    testcase.assertEqual(metadata["revision_semantics"], revision_semantics)
