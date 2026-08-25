from datetime import datetime, timezone
import unittest

from investment_monitor.content_relevance import (
    CONTENT_RELEVANCE_PROMPT_VERSION,
    ContentRelevanceError,
    ContentRelevanceFilter,
    content_relevance_filter_from_environment,
)
from investment_monitor.models import InformationItem
from investment_monitor.research import ResearchSettings


class FakeClient:
    def __init__(self, response, model="fake-relevance-model"):
        self.response = response
        self.model = model
        self.calls = []

    def generate(self, *, system_prompt, user_prompt, language):
        self.calls.append((system_prompt, user_prompt, language))
        return self.response


def item(identifier, *, source_type="news", title="Company announces contract"):
    return InformationItem(
        source="fixture",
        source_type=source_type,
        external_id=identifier,
        tickers=("ACME",),
        issuer="Acme Corp",
        published_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        title=title,
        document_type="article",
        url="https://example.test/" + identifier,
        collected_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        raw_metadata={"origin": "fixture"},
    )


class ContentRelevanceFilterTests(unittest.TestCase):
    def test_keeps_primary_roles_and_records_structured_metadata(self):
        client = FakeClient({"results": [
            {"id": "0", "decision": "include", "role": "primary_subject", "reason": "Acme is the announced company."},
            {"id": "1", "decision": "include", "role": "primary_affected", "reason": "The contract directly changes Acme supply."},
            {"id": "2", "decision": "exclude", "role": "incidental", "reason": "Acme is only mentioned."},
        ]})
        original = [item("subject"), item("affected"), item("incidental")]

        result = ContentRelevanceFilter(client=client).filter(original)

        self.assertEqual([record.external_id for record in result], ["subject", "affected"])
        self.assertIsNot(result[0], original[0])
        self.assertEqual(original[0].raw_metadata, {"origin": "fixture"})
        relevance = result[0].raw_metadata["content_relevance"]
        self.assertEqual(relevance["decision"], "include")
        self.assertEqual(relevance["role"], "primary_subject")
        self.assertEqual(relevance["model"], "fake-relevance-model")
        self.assertEqual(relevance["prompt_version"], CONTENT_RELEVANCE_PROMPT_VERSION)
        self.assertEqual(len(client.calls), 1)
        self.assertIn("incidental", client.calls[0][0])
        self.assertIn("primary_affected", client.calls[0][0])

    def test_numeric_item_ids_are_accepted(self):
        client = FakeClient({"results": [
            {"id": 0, "decision": "include", "role": "primary_subject", "reason": "Acme is the announced company."},
            {"id": 1, "decision": "exclude", "role": "incidental", "reason": "Acme is only mentioned."},
        ]})

        result = ContentRelevanceFilter(client=client).filter(
            [item("subject"), item("incidental")]
        )

        self.assertEqual([record.external_id for record in result], ["subject"])

    def test_excludes_list_comparison_ambiguous_and_insufficient_context(self):
        roles = ["list", "comparison", "ambiguous", "insufficient_context"]
        client = FakeClient({"results": [
            {"id": str(index), "decision": "exclude", "role": role, "reason": role}
            for index, role in enumerate(roles)
        ]})

        self.assertEqual(ContentRelevanceFilter(client=client).filter(
            [item(role) for role in roles]
        ), [])

    def test_malformed_missing_duplicate_or_illegal_response_fails_closed(self):
        cases = [
            {"results": []},
            {"results": [
                {"id": "0", "decision": "include", "role": "primary_subject", "reason": "ok"},
                {"id": "0", "decision": "exclude", "role": "incidental", "reason": "duplicate"},
            ]},
            {"results": [{"id": "0", "decision": "include", "role": "incidental", "reason": "bad pair"}]},
        ]
        for response in cases:
            with self.subTest(response=response):
                with self.assertRaises(ContentRelevanceError):
                    ContentRelevanceFilter(client=FakeClient(response)).filter([item("one")])

    def test_non_news_and_non_community_items_bypass_model_unchanged(self):
        client = FakeClient({"results": []})
        filing = item("filing", source_type="regulatory_filing")

        result = ContentRelevanceFilter(client=client).filter([filing])

        self.assertEqual(result, [filing])
        self.assertIs(result[0], filing)
        self.assertEqual(client.calls, [])

    def test_environment_factory_is_explicit_and_requires_key_when_enabled(self):
        self.assertIsNone(content_relevance_filter_from_environment({}))
        with self.assertRaises(ValueError):
            content_relevance_filter_from_environment({"CONTENT_RELEVANCE_AI_ENABLED": "maybe"})
        with self.assertRaisesRegex(ValueError, "RESEARCH_AI_API_KEY"):
            content_relevance_filter_from_environment({"CONTENT_RELEVANCE_AI_ENABLED": "true"})
        result = content_relevance_filter_from_environment({
            "CONTENT_RELEVANCE_AI_ENABLED": "true",
            "RESEARCH_AI_API_KEY": "test-key",
        })
        self.assertIsInstance(result, ContentRelevanceFilter)


if __name__ == "__main__":
    unittest.main()
