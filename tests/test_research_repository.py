from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import threading
import time
import unittest
from unittest.mock import patch

from investment_monitor.models import InformationItem
from investment_monitor.sqlite_repository import SQLiteInformationRepository
from investment_monitor.web_repository import WebRepository
from investment_monitor.research import (
    ResearchSettings,
    ResearchEvidence,
    MAX_PROMPT_BYTES,
    build_system_prompt,
    build_user_prompt,
    evidence_fingerprint,
    select_evidence,
    selectable_status,
    validate_research_card,
)
from investment_monitor.research_repository import (
    ResearchRepository,
    ensure_research_schema,
)
from investment_monitor.research_service import ResearchService, validate_list_slug


class FakeResolver:
    def resolve(self, ticker):
        ticker = ticker.upper()
        return {
            "ticker": ticker,
            "name": f"{ticker} Inc.",
            "exchange": "Nasdaq",
            "cik": "",
            "mapping_status": "mapped",
        }


class FakeAI:
    def __init__(self, card=None, error=None):
        self.card = card or DEFAULT_CARD
        self.error = error
        self.calls = []

    def generate(self, *, system_prompt, user_prompt, language):
        self.calls.append(
            {"system": system_prompt, "user": user_prompt, "language": language}
        )
        if self.error is not None:
            raise self.error
        return self.card


DEFAULT_CARD = {
    "schema_version": "research-card-v1",
    "language": "en",
    "coverage": {"summary": "A summary.", "limitations": ["Limited."]},
    "recent_changes": [
        {
            "title": "A change",
            "summary": "What changed.",
            "claim_type": "direct_disclosure_fact",
            "evidence_ids": ["E1"],
        }
    ],
    "main_risks": [
        {
            "category": "regulatory",
            "title": "A risk",
            "explanation": "Why it matters.",
            "evidence_strength": "high",
            "claim_type": "direct_disclosure_fact",
            "evidence_ids": ["E1"],
        }
    ],
    "volatility_drivers": [
        {
            "trigger": "A trigger",
            "why_it_matters": "Why.",
            "signals_to_watch": ["A signal"],
            "claim_type": "cautious_inference",
            "evidence_ids": ["E1"],
        }
    ],
    "questions_to_investigate": [
        {
            "question": "A question",
            "reason": "Why ask.",
            "evidence_ids": ["E1"],
        }
    ],
}


class BlockingAI:
    """An AI that blocks inside generate() so the worker's frozen selection can be inspected."""

    def __init__(self, card=None):
        self.card = card or DEFAULT_CARD
        self.started = threading.Event()
        self.release = threading.Event()
        self.prompts = []

    def generate(self, *, system_prompt, user_prompt, language):
        self.prompts.append(user_prompt)
        self.started.set()
        self.release.wait(timeout=10)
        return self.card


def make_item_dict(
    item_id,
    *,
    source="sec",
    source_type="regulatory_filing",
    title="A filing",
    effective_at=None,
    published_at="2026-01-01T12:00:00+00:00",
    acceptance=None,
    summary=None,
):
    metadata = {}
    if acceptance:
        metadata["acceptanceDateTime"] = acceptance
    return {
        "id": item_id,
        "source": source,
        "source_type": source_type,
        "title": title,
        "url": f"https://example.com/{item_id}",
        "published_at": published_at,
        "effective_at": effective_at,
        "raw_metadata": metadata,
        "summary": summary,
    }


class EvidenceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.settings = ResearchSettings()

    def test_selects_and_sorts_by_event_timestamp_descending(self):
        items = [
            make_item_dict(1, effective_at="2026-01-01T00:00:00+00:00"),
            make_item_dict(2, effective_at="2026-03-01T00:00:00+00:00"),
            make_item_dict(3, effective_at="2026-02-01T00:00:00+00:00"),
        ]
        selection = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertEqual([e.ref for e in selection.evidence], ["E1", "E2", "E3"])
        self.assertEqual([e.item_id for e in selection.evidence], [2, 3, 1])

    def test_effective_at_wins_over_acceptance_and_published(self):
        # Same item with three candidate times; only effective_at is used.
        items = [
            make_item_dict(
                1,
                effective_at="2026-05-01T00:00:00+00:00",
                acceptance="2030-01-01T00:00:00+00:00",
                published_at="2020-01-01T00:00:00+00:00",
            )
        ]
        selection = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(selection.evidence[0].event_at, datetime(2026, 5, 1, tzinfo=timezone.utc))

    def test_acceptance_used_when_no_effective_at(self):
        items = [
            make_item_dict(
                1,
                acceptance="2026-06-01T00:00:00+00:00",
                published_at="2020-01-01T00:00:00+00:00",
            )
        ]
        selection = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(selection.evidence[0].event_at, datetime(2026, 6, 1, tzinfo=timezone.utc))

    def test_collected_at_is_never_the_event_time(self):
        # A 10-year-old filing must fall outside the lookback even though its
        # collection time (collected_at) is recent. collected_at is not passed
        # to the selector at all; only the stored event fields count.
        items = [
            make_item_dict(
                1,
                effective_at="2010-01-01T00:00:00+00:00",
            )
        ]
        selection = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(selection.total, 0)

    def test_lookback_boundary_inclusive(self):
        settings = ResearchSettings(lookback_days=365)
        items = [
            make_item_dict(1, effective_at="2025-08-02T00:00:00+00:00"),
        ]
        selection = select_evidence(
            items, company_id=1, language="en", settings=settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(selection.total, 1)

    def test_lookback_boundary_exclusive(self):
        settings = ResearchSettings(lookback_days=365)
        items = [
            make_item_dict(1, effective_at="2025-07-31T23:59:59+00:00"),
        ]
        selection = select_evidence(
            items, company_id=1, language="en", settings=settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(selection.total, 0)

    def test_max_items_cap(self):
        settings = ResearchSettings(max_evidence_items=5, min_evidence_items=3)
        items = [
            make_item_dict(i, effective_at=f"2026-07-{i:02d}T00:00:00+00:00")
            for i in range(1, 21)
        ]
        selection = select_evidence(
            items, company_id=1, language="en", settings=settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(selection.total, 5)
        self.assertEqual(selection.evidence[0].item_id, 20)

    def test_insufficient_evidence_when_below_minimum(self):
        items = [make_item_dict(1), make_item_dict(2)]
        selection = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertFalse(selection.eligible)

    def test_community_only_is_not_eligible(self):
        items = [
            make_item_dict(1, source="xueqiu", source_type="community"),
            make_item_dict(2, source="xueqiu", source_type="community"),
            make_item_dict(3, source="xueqiu", source_type="community"),
        ]
        selection = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertFalse(selection.eligible)
        self.assertEqual(selection.community_count, 3)

    def test_news_only_is_eligible_but_flagged(self):
        items = [
            make_item_dict(1, source="news", source_type="news"),
            make_item_dict(2, source="news", source_type="news"),
            make_item_dict(3, source="news", source_type="news"),
        ]
        selection = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertTrue(selection.eligible)
        self.assertTrue(selection.news_only)

    def test_fingerprint_is_stable(self):
        items = [
            make_item_dict(1, effective_at="2026-01-01T00:00:00+00:00"),
            make_item_dict(2, effective_at="2026-02-01T00:00:00+00:00"),
        ]
        selection_a = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        selection_b = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(selection_a.fingerprint, selection_b.fingerprint)

    def test_fingerprint_changes_when_evidence_changes(self):
        base = [
            make_item_dict(1, effective_at="2026-01-01T00:00:00+00:00"),
            make_item_dict(2, effective_at="2026-02-01T00:00:00+00:00"),
            make_item_dict(3, effective_at="2026-03-01T00:00:00+00:00"),
        ]
        original = select_evidence(
            base, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        ).fingerprint
        added = select_evidence(
            base + [make_item_dict(4, effective_at="2026-04-01T00:00:00+00:00")],
            company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        ).fingerprint
        self.assertNotEqual(original, added)

    def test_fingerprint_changes_when_summary_changes(self):
        def items_with_summary(summary):
            return [
                make_item_dict(1, summary=summary, effective_at="2026-01-01T00:00:00+00:00"),
                make_item_dict(2, effective_at="2026-02-01T00:00:00+00:00"),
                make_item_dict(3, effective_at="2026-03-01T00:00:00+00:00"),
            ]
        a = select_evidence(
            items_with_summary("summary A"), company_id=1, language="en",
            settings=self.settings, now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        ).fingerprint
        b = select_evidence(
            items_with_summary("summary B"), company_id=1, language="en",
            settings=self.settings, now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        ).fingerprint
        self.assertNotEqual(a, b)

    def test_fingerprint_differs_by_language(self):
        items = [
            make_item_dict(1, effective_at="2026-01-01T00:00:00+00:00"),
            make_item_dict(2, effective_at="2026-02-01T00:00:00+00:00"),
            make_item_dict(3, effective_at="2026-03-01T00:00:00+00:00"),
        ]
        en = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        ).fingerprint
        zh = select_evidence(
            items, company_id=1, language="zh-CN", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        ).fingerprint
        self.assertNotEqual(en, zh)

    def test_fingerprint_differs_by_model_and_version(self):
        items = [
            make_item_dict(1, effective_at="2026-01-01T00:00:00+00:00"),
            make_item_dict(2, effective_at="2026-02-01T00:00:00+00:00"),
            make_item_dict(3, effective_at="2026-03-01T00:00:00+00:00"),
        ]
        base = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        other_model = select_evidence(
            items, company_id=1, language="en",
            settings=ResearchSettings(model="other-model"),
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertNotEqual(base.fingerprint, other_model.fingerprint)

    def test_duplicate_rows_are_kept(self):
        # Soft-dedupe semantics: rows are never merged or dropped.
        items = [
            make_item_dict(1, title="Same title"),
            make_item_dict(2, title="Same title"),
            make_item_dict(3, title="Same title"),
        ]
        selection = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(selection.total, 3)

    def test_long_title_truncated(self):
        items = [
            make_item_dict(1, title="x" * 1000, effective_at="2026-01-01T00:00:00+00:00"),
            make_item_dict(2, effective_at="2026-02-01T00:00:00+00:00"),
            make_item_dict(3, effective_at="2026-03-01T00:00:00+00:00"),
        ]
        selection = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        item1 = [e for e in selection.evidence if e.item_id == 1][0]
        self.assertLessEqual(len(item1.title), 500)

    def test_long_summary_truncated(self):
        items = [
            make_item_dict(1, summary="s" * 5000, effective_at="2026-01-01T00:00:00+00:00"),
            make_item_dict(2, effective_at="2026-02-01T00:00:00+00:00"),
            make_item_dict(3, effective_at="2026-03-01T00:00:00+00:00"),
        ]
        selection = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        item1 = [e for e in selection.evidence if e.item_id == 1][0]
        self.assertLessEqual(len(item1.summary), 2000)

    def test_total_prompt_budget_capped(self):
        # 120 items with large CJK titles+summaries exceed the 512KB budget, so
        # the selector must stop adding evidence before the cap.
        items = [
            make_item_dict(
                i,
                title="中" * 500,
                summary="文" * 2000,
                effective_at=f"2026-01-01T00:00:00+00:00",
            )
            for i in range(1, 121)
        ]
        selection = select_evidence(
            items, company_id=1, language="en", settings=self.settings,
            now=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        self.assertLess(selection.total, 120)

    def test_actual_prompt_within_budget(self):
        import investment_monitor.research as research_mod
        with patch.object(research_mod, "MAX_PROMPT_BYTES", 4000):
            items = [
                make_item_dict(
                    i,
                    title="中文标题" * 40,
                    summary="中文摘要" * 80,
                    effective_at=f"2026-01-01T00:00:00+00:00",
                )
                for i in range(1, 60)
            ]
            selection = select_evidence(
                items, company_id=1, language="zh-CN", settings=self.settings,
                now=datetime(2026, 8, 1, tzinfo=timezone.utc),
                company_name="测试公司", ticker="TEST", market="cn",
            )
            system = build_system_prompt("zh-CN")
            user = build_user_prompt(
                company_name="测试公司", ticker="TEST", market="cn",
                language="zh-CN", evidence=selection.evidence, news_only=False,
            )
            total = len(system.encode("utf-8")) + len(user.encode("utf-8"))
            self.assertLessEqual(total, 4000)

    def test_truncation_below_minimum_returns_insufficient(self):
        import investment_monitor.research as research_mod
        with patch.object(research_mod, "MAX_PROMPT_BYTES", 120):
            items = [
                make_item_dict(i, title="x" * 500, effective_at=f"2026-01-01T00:00:00+00:00")
                for i in range(1, 10)
            ]
            selection = select_evidence(
                items, company_id=1, language="en", settings=self.settings,
                now=datetime(2026, 8, 1, tzinfo=timezone.utc),
                company_name="Apple", ticker="AAPL", market="us",
            )
            # 预算极小，能保留的证据少于 min_evidence_items(3)
            self.assertFalse(selection.eligible)


FILING_REF = {
    "E1": {"item_id": 1, "source": "sec", "source_type": "regulatory_filing", "information_type": "filing"}
}
NEWS_REF = {
    "E1": {"item_id": 1, "source": "news", "source_type": "news", "information_type": "news"}
}
COMMUNITY_REF = {
    "E1": {"item_id": 1, "source": "xueqiu", "source_type": "community", "information_type": "community"}
}
MIXED_REFS = {
    "E1": {"item_id": 1, "source": "sec", "source_type": "regulatory_filing", "information_type": "filing"},
    "E2": {"item_id": 2, "source": "news", "source_type": "news", "information_type": "news"},
    "E3": {"item_id": 3, "source": "xueqiu", "source_type": "community", "information_type": "community"},
}


class CardValidationTests(unittest.TestCase):
    def test_valid_card_passes(self):
        card = validate_research_card(
            DEFAULT_CARD, language="en", allowed_refs=FILING_REF
        )
        self.assertEqual(card["schema_version"], "research-card-v1")

    def test_unknown_evidence_id_rejected(self):
        with self.assertRaises(ValueError):
            validate_research_card(DEFAULT_CARD, language="en", allowed_refs={})

    def test_wrong_language_rejected(self):
        with self.assertRaises(ValueError):
            validate_research_card(
                DEFAULT_CARD, language="zh-CN", allowed_refs=FILING_REF
            )

    def test_illegal_claim_type_rejected(self):
        card = copy.deepcopy(DEFAULT_CARD)
        card["recent_changes"] = [
            {
                "title": "t",
                "summary": "s",
                "claim_type": "buy_recommendation",
                "evidence_ids": ["E1"],
            }
        ]
        with self.assertRaises(ValueError):
            validate_research_card(card, language="en", allowed_refs=FILING_REF)

    def test_illegal_strength_rejected(self):
        card = copy.deepcopy(DEFAULT_CARD)
        card["main_risks"] = [
            {
                "category": "regulatory",
                "title": "t",
                "explanation": "e",
                "evidence_strength": "extreme",
                "claim_type": "direct_disclosure_fact",
                "evidence_ids": ["E1"],
            }
        ]
        with self.assertRaises(ValueError):
            validate_research_card(card, language="en", allowed_refs=FILING_REF)

    def test_script_content_rejected(self):
        card = copy.deepcopy(DEFAULT_CARD)
        card["coverage"]["summary"] = "<script>alert(1)</script>"
        with self.assertRaises(ValueError):
            validate_research_card(card, language="en", allowed_refs=FILING_REF)

    def test_unknown_top_level_field_rejected(self):
        card = copy.deepcopy(DEFAULT_CARD)
        card["target_price"] = 100
        with self.assertRaises(ValueError):
            validate_research_card(card, language="en", allowed_refs=FILING_REF)

    # --- P0-4: claim_type must match the cited evidence source kind ---

    @staticmethod
    def _minimal_card(recent_claim_type, recent_evidence_ids):
        # main_risks / volatility use cautious_inference so they never conflict
        # with the single evidence type under test.
        return {
            "schema_version": "research-card-v1",
            "language": "en",
            "coverage": {"summary": "s", "limitations": ["l"]},
            "recent_changes": [
                {"title": "t", "summary": "s", "claim_type": recent_claim_type, "evidence_ids": recent_evidence_ids}
            ],
            "main_risks": [
                {"category": "regulatory", "title": "t", "explanation": "e", "evidence_strength": "high", "claim_type": "cautious_inference", "evidence_ids": ["E1"]}
            ],
            "volatility_drivers": [
                {"trigger": "t", "why_it_matters": "w", "signals_to_watch": ["s"], "claim_type": "cautious_inference", "evidence_ids": ["E1"]}
            ],
            "questions_to_investigate": [
                {"question": "q", "reason": "r", "evidence_ids": ["E1"]}
            ],
        }

    def test_community_direct_disclosure_fact_rejected(self):
        card = self._minimal_card("direct_disclosure_fact", ["E1"])
        with self.assertRaises(ValueError):
            validate_research_card(card, language="en", allowed_refs=COMMUNITY_REF)

    def test_community_reported_news_rejected(self):
        card = self._minimal_card("reported_news", ["E1"])
        with self.assertRaises(ValueError):
            validate_research_card(card, language="en", allowed_refs=COMMUNITY_REF)

    def test_filing_direct_disclosure_fact_allowed(self):
        card = self._minimal_card("direct_disclosure_fact", ["E1"])
        result = validate_research_card(card, language="en", allowed_refs=FILING_REF)
        self.assertEqual(result["recent_changes"][0]["claim_type"], "direct_disclosure_fact")

    def test_news_reported_news_allowed(self):
        card = self._minimal_card("reported_news", ["E1"])
        result = validate_research_card(card, language="en", allowed_refs=NEWS_REF)
        self.assertEqual(result["recent_changes"][0]["claim_type"], "reported_news")

    def test_community_community_viewpoint_allowed(self):
        card = self._minimal_card("community_viewpoint", ["E1"])
        result = validate_research_card(card, language="en", allowed_refs=COMMUNITY_REF)
        self.assertEqual(result["recent_changes"][0]["claim_type"], "community_viewpoint")

    def test_cautious_inference_mixed_sources_allowed(self):
        card = self._minimal_card("cautious_inference", ["E1", "E2", "E3"])
        result = validate_research_card(card, language="en", allowed_refs=MIXED_REFS)
        self.assertEqual(
            result["recent_changes"][0]["evidence_ids"], ["E1", "E2", "E3"]
        )

    def test_system_prompt_has_untrusted_data_instruction(self):
        en = build_system_prompt("en")
        zh = build_system_prompt("zh-CN")
        self.assertIn("untrusted data", en)
        self.assertIn("Never present Community evidence as a Filing", en)
        self.assertIn("不可信数据", zh)
        self.assertIn("绝不能把 Community 证据说成 Filing", zh)


class ResearchRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "web.sqlite3"
        self.items = SQLiteInformationRepository(self.database_path)
        self.repository = WebRepository(self.database_path)
        self.resolver = FakeResolver()
        self.research = ResearchRepository(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def add_company(self, ticker, *lists):
        result = self.repository.add_companies_batch(ticker, lists, self.resolver)
        self.assertFalse(result["failed"])
        return result["added"][0]["ticker"] if result["added"] else ticker.upper()

    def save_item(self, item):
        self.items.save((item,))

    def test_research_items_scoped_to_current_company(self):
        self.add_company("AAPL", "holdings")
        self.add_company("MSFT", "holdings")
        self.save_item(InformationItem(
            source="sec", source_type="regulatory_filing",
            external_id="aapl-1", tickers=("AAPL",), issuer="AAPL Inc.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            title="AAPL filing", document_type="8-K",
            url="https://example.com/aapl", collected_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ))
        self.save_item(InformationItem(
            source="sec", source_type="regulatory_filing",
            external_id="msft-1", tickers=("MSFT",), issuer="MSFT Inc.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            title="MSFT filing", document_type="8-K",
            url="https://example.com/msft", collected_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ))
        aapl_id = self.repository.companies()[0]["id"]
        aapl = [c for c in self.repository.companies() if c["ticker"] == "AAPL"][0]
        items = self.repository.research_items(aapl["id"])
        self.assertTrue(all(i["title"] == "AAPL filing" for i in items))
        self.assertEqual(len(items), 1)

    def test_research_items_exclude_generated(self):
        self.add_company("AAPL", "holdings")
        self.save_item(InformationItem(
            source="sec", source_type="regulatory_filing",
            external_id="gen-1", tickers=("AAPL",), issuer="AAPL Inc.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            title="generated filing", document_type="8-K",
            url="https://example.com/gen", collected_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            raw_metadata={"generated": True},
        ))
        aapl = [c for c in self.repository.companies() if c["ticker"] == "AAPL"][0]
        self.assertEqual(len(self.repository.research_items(aapl["id"])), 0)

    def test_research_items_exclude_unsupported_source_type(self):
        self.add_company("AAPL", "holdings")
        self.save_item(InformationItem(
            source="sec", source_type="research",
            external_id="res-1", tickers=("AAPL",), issuer="AAPL Inc.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            title="research note", document_type="note",
            url="https://example.com/res", collected_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ))
        aapl = [c for c in self.repository.companies() if c["ticker"] == "AAPL"][0]
        self.assertEqual(len(self.repository.research_items(aapl["id"])), 0)

    def test_research_items_exclude_non_allowed_source(self):
        # Default allowed_sources is ("sec",); a mock source row must not appear.
        self.add_company("AAPL", "holdings")
        self.save_item(InformationItem(
            source="mock_community", source_type="community",
            external_id="mock-1", tickers=("AAPL",), issuer="AAPL Inc.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            title="mock post", document_type="post",
            url="https://example.com/mock", collected_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ))
        aapl = [c for c in self.repository.companies() if c["ticker"] == "AAPL"][0]
        self.assertEqual(len(self.repository.research_items(aapl["id"])), 0)

    # --- P0-3: strict company/market isolation ---

    def _add_unknown_item(self, ticker):
        self.save_item(InformationItem(
            source="sec", source_type="regulatory_filing",
            external_id=f"{ticker}-unknown", tickers=(ticker,), issuer=f"{ticker} Inc.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            title=f"{ticker} unknown", document_type="8-K",
            url=f"https://example.com/{ticker}-unknown",
            collected_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            market="unknown",
        ))

    def test_unknown_item_excluded_when_ticker_in_multiple_markets(self):
        self.add_company("ABC", "holdings")  # market=us
        result = self.repository.add_companies_batch(
            "ABC", ("holdings",), self.resolver, market="hk"
        )
        self.assertFalse(result["failed"])
        self._add_unknown_item("ABC")
        for company in self.repository.companies():
            self.assertEqual(len(self.repository.research_items(company["id"])), 0)

    def test_unknown_item_allowed_when_ticker_unique(self):
        self.add_company("ABC", "holdings")  # only market=us
        self._add_unknown_item("ABC")
        abc = [c for c in self.repository.companies() if c["ticker"] == "ABC"][0]
        items = self.repository.research_items(abc["id"])
        self.assertEqual(len(items), 1)

    def test_strict_market_item_still_used(self):
        self.add_company("ABC", "holdings")  # market=us
        self.save_item(InformationItem(
            source="sec", source_type="regulatory_filing",
            external_id="abc-us", tickers=("ABC",), issuer="ABC Inc.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            title="ABC us", document_type="8-K",
            url="https://example.com/abc-us",
            collected_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            market="us",
        ))
        abc = [c for c in self.repository.companies() if c["ticker"] == "ABC"][0]
        items = self.repository.research_items(abc["id"])
        self.assertEqual(len(items), 1)

    def test_persist_and_recover_interrupted(self):
        self.add_company("AAPL", "holdings")
        company_id = self.repository.companies()[0]["id"]
        card_id = self.research.create_generation(
            company_id=company_id, language="en", evidence_fingerprint="fp",
            model_provider_fingerprint="provider", model_name="model",
        )
        self.assertTrue(self.research.has_in_progress(company_id, "en"))
        recovered = self.research.recover_interrupted()
        self.assertEqual(recovered, 1)
        self.assertFalse(self.research.has_in_progress(company_id, "en"))
        card = self.research.latest_card(company_id, "en")
        self.assertEqual(card["status"], "failed")
        self.assertEqual(card["error_code"], "generation_interrupted")


class ResearchServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "web.sqlite3"
        self.items = SQLiteInformationRepository(self.database_path)
        self.repository = WebRepository(self.database_path)
        self.resolver = FakeResolver()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def add_company(self, ticker, *lists):
        result = self.repository.add_companies_batch(ticker, lists, self.resolver)
        self.assertFalse(result["failed"])

    def save_item(self, item):
        self.items.save((item,))

    def build_service(self, ai=None, settings=None):
        return ResearchService(
            self.repository,
            self.database_path,
            settings or ResearchSettings(),
            ai_client=ai,
            synchronous=True,
        )

    def test_non_list_company_cannot_generate(self):
        # Company exists but belongs to no fixed list.
        result = self.repository.add_companies_batch(
            "AAPL", ("holdings",), self.resolver
        )
        # Remove it from holdings so it is not in any fixed list.
        self.repository.remove_all_memberships("AAPL")
        service = self.build_service()
        with self.assertRaises(ValueError):
            service.generate(1, "en", force=False)

    def test_companies_only_returns_fixed_list_members(self):
        self.add_company("AAPL", "holdings")
        self.add_company("MSFT", "planned")
        self.add_company("NVDA", "watchlist")
        service = self.build_service()
        companies = service.companies(None, "en")
        self.assertEqual({c["ticker"] for c in companies}, {"AAPL", "MSFT", "NVDA"})
        # All lists dedupe the same company.
        self.add_company("AAPL", "planned")
        companies = service.companies(None, "en")
        aapl_rows = [c for c in companies if c["ticker"] == "AAPL"]
        self.assertEqual(len(aapl_rows), 1)

    def test_list_filter(self):
        self.add_company("AAPL", "holdings")
        self.add_company("MSFT", "planned")
        service = self.build_service()
        holdings = service.companies("holdings", "en")
        self.assertEqual([c["ticker"] for c in holdings], ["AAPL"])

    def test_no_list_company_invisible(self):
        self.add_company("AAPL", "holdings")
        self.repository.remove_all_memberships("AAPL")
        service = self.build_service()
        self.assertEqual([c["ticker"] for c in service.companies(None, "en")], [])

    def test_custom_list_only_company_invisible(self):
        custom = self.repository.create_list("My Custom")
        result = self.repository.add_companies_batch(
            "AAPL", (custom["slug"],), self.resolver
        )
        self.assertFalse(result["failed"])
        service = self.build_service()
        self.assertEqual([c["ticker"] for c in service.companies(None, "en")], [])

    def test_holdings_watchlist_company_appears_once_in_all(self):
        self.add_company("AAPL", "holdings")
        self.add_company("AAPL", "watchlist")
        service = self.build_service()
        aapl_rows = [c for c in service.companies(None, "en") if c["ticker"] == "AAPL"]
        self.assertEqual(len(aapl_rows), 1)

    def test_invalid_list_slug_rejected(self):
        with self.assertRaises(ValueError):
            validate_list_slug("custom-list")

    def test_disabled_service_returns_error(self):
        self.add_company("AAPL", "holdings")
        service = self.build_service(settings=ResearchSettings(enabled=False))
        result = service.generate(1, "en")
        self.assertEqual(result["code"], "research_disabled")

    def test_not_configured_returns_error(self):
        self.add_company("AAPL", "holdings")
        service = self.build_service(settings=ResearchSettings(enabled=True, api_key=""))
        result = service.generate(1, "en")
        self.assertEqual(result["code"], "model_not_configured")

    def test_generate_caches_on_same_fingerprint(self):
        self.add_company("AAPL", "holdings")
        for i in range(3):
            self.save_item(InformationItem(
                source="sec", source_type="regulatory_filing",
                external_id=f"f{i}", tickers=("AAPL",), issuer="AAPL Inc.",
                published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                title=f"filing {i}", document_type="8-K",
                url=f"https://example.com/{i}", collected_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ))
        ai = FakeAI()
        service = self.build_service(ai=ai, settings=ResearchSettings(enabled=True, api_key="k"))
        aapl = [c for c in self.repository.companies() if c["ticker"] == "AAPL"][0]
        first = service.generate(aapl["id"], "en")
        self.assertEqual(first["status"], "completed")
        self.assertEqual(len(ai.calls), 1)
        second = service.generate(aapl["id"], "en")
        self.assertEqual(second["status"], "cached")
        self.assertEqual(len(ai.calls), 1)

    def test_regenerate_bypasses_cache(self):
        self.add_company("AAPL", "holdings")
        for i in range(3):
            self.save_item(InformationItem(
                source="sec", source_type="regulatory_filing",
                external_id=f"f{i}", tickers=("AAPL",), issuer="AAPL Inc.",
                published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                title=f"filing {i}", document_type="8-K",
                url=f"https://example.com/{i}", collected_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ))
        ai = FakeAI()
        service = self.build_service(ai=ai, settings=ResearchSettings(enabled=True, api_key="k"))
        aapl = [c for c in self.repository.companies() if c["ticker"] == "AAPL"][0]
        first = service.generate(aapl["id"], "en")
        second = service.generate(aapl["id"], "en", force=True)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(len(ai.calls), 2)

    # --- P1-1: frozen evidence snapshot ---

    def _seed_filings(self, count):
        seq = getattr(self, "_seed_seq", 0)
        for _ in range(count):
            self.save_item(InformationItem(
                source="sec", source_type="regulatory_filing",
                external_id=f"seed-{seq}", tickers=("AAPL",), issuer="AAPL Inc.",
                published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                title=f"filing {seq}", document_type="8-K",
                url=f"https://example.com/{seq}", collected_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ))
            seq += 1
        self._seed_seq = seq

    def _delete_item(self, external_id):
        with self.repository._connect() as connection:
            connection.execute(
                "DELETE FROM information_items WHERE external_id = ?",
                (external_id,),
            )

    def _async_service(self, ai):
        return ResearchService(
            self.repository,
            self.database_path,
            ResearchSettings(enabled=True, api_key="k"),
            ai_client=ai,
            synchronous=False,
        )

    @staticmethod
    def _wait_generation(service, generation_id):
        for _ in range(200):
            status = service.generation_status(generation_id)
            if status["status"] != "generating":
                return status
            time.sleep(0.02)
        return service.generation_status(generation_id)

    def test_frozen_snapshot_when_evidence_added_during_queue(self):
        self.add_company("AAPL", "holdings")
        self._seed_filings(3)
        ai = BlockingAI()
        service = self._async_service(ai)
        try:
            aapl = [c for c in self.repository.companies() if c["ticker"] == "AAPL"][0]
            result = service.generate(aapl["id"], "en", force=True)
            self.assertEqual(result["status"], "generating")
            ai.started.wait(timeout=5)
            self._seed_filings(1)  # add a 4th item while the worker is frozen
            ai.release.set()
            status = self._wait_generation(service, result["generation_id"])
            self.assertEqual(status["status"], "completed")
            card = service.card(result["generation_id"])
            # Frozen: snapshot and prompt use the original 3, not the new 4th.
            self.assertEqual(len(card["evidence"]), 3)
            self.assertEqual(ai.prompts[0].count("[E"), 3)
        finally:
            service.shutdown()

    def test_frozen_snapshot_when_evidence_removed_during_queue(self):
        self.add_company("AAPL", "holdings")
        self._seed_filings(3)
        ai = BlockingAI()
        service = self._async_service(ai)
        try:
            aapl = [c for c in self.repository.companies() if c["ticker"] == "AAPL"][0]
            result = service.generate(aapl["id"], "en", force=True)
            ai.started.wait(timeout=5)
            self._delete_item("seed-2")  # remove an item while frozen
            ai.release.set()
            status = self._wait_generation(service, result["generation_id"])
            self.assertEqual(status["status"], "completed")
            card = service.card(result["generation_id"])
            self.assertEqual(len(card["evidence"]), 3)
        finally:
            service.shutdown()

    def test_removed_from_lists_before_model_call_fails_safely(self):
        self.add_company("AAPL", "holdings")
        self._seed_filings(3)
        ai = FakeAI()
        service = self.build_service(ai=ai, settings=ResearchSettings(enabled=True, api_key="k"))
        aapl = [c for c in self.repository.companies() if c["ticker"] == "AAPL"][0]
        selection = service._select(aapl["id"], "en")
        card_id = service._repo.create_generation(
            company_id=aapl["id"], language="en",
            evidence_fingerprint=selection.fingerprint,
            model_provider_fingerprint="p", model_name="m",
        )
        self.repository.remove_all_memberships("AAPL")
        service._run_generation(card_id, aapl["id"], "en", selection)
        self.assertEqual(len(ai.calls), 0)
        card = service._repo.latest_card(aapl["id"], "en")
        self.assertEqual(card["status"], "failed")
        self.assertEqual(card["error_code"], "no_eligible_evidence")


if __name__ == "__main__":
    unittest.main()
