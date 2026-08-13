"""Daily <-> Research scope parity tests.

For the same company_id + start_date + end_date + list scope, the following
four sets must be strictly equal, item by item:

1. the display rows Daily actually shows for the company;
2. the Research candidate evidence for the company;
3. the evidence the (fake) model actually receives;
4. the research_card_evidence snapshot saved with the card.

No count-based truncation exists anywhere in this chain. An over-large range
fails honestly with research_range_too_large instead of dropping items.
"""

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from investment_monitor.application import ConfiguredCollectionResult
from investment_monitor.models import InformationItem
from investment_monitor.repository import SaveResult
from investment_monitor.research import ResearchScope, ResearchSettings
from investment_monitor.sqlite_repository import SQLiteInformationRepository
from investment_monitor.web import WebApplication


FIXED_NOW = datetime(2026, 8, 13, 3, 0, tzinfo=timezone.utc)  # 2026-08-13 in Shanghai
START = date(2026, 8, 10)
END = date(2026, 8, 13)
SCOPE = ResearchScope(START, END)
RANGE_QUERY = "start_date=2026-08-10&end_date=2026-08-13"

SAME_ORIGIN_HEADERS = {
    "Content-Type": "application/json",
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
}

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
            "explanation": "Why.",
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
        {"question": "A question", "reason": "Why ask.", "evidence_ids": ["E1"]}
    ],
}


class FakeAI:
    def __init__(self, card=None):
        self.card = card or DEFAULT_CARD
        self.calls = []

    def generate(self, *, system_prompt, user_prompt, language):
        self.calls.append(
            {"system": system_prompt, "user": user_prompt, "language": language}
        )
        return self.card


def make_item(
    external_id,
    *,
    tickers=("AAPL",),
    source="sec",
    source_type="regulatory_filing",
    title=None,
    published_at=datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc),
    effective_at=None,
    calendar_date=None,
    generated=False,
    market="us",
):
    metadata = {}
    if calendar_date is not None:
        metadata["calendar_date"] = calendar_date
    if generated:
        metadata["generated"] = True
    return InformationItem(
        source=source,
        source_type=source_type,
        external_id=external_id,
        tickers=tickers,
        issuer="Issuer",
        published_at=published_at,
        title=title or f"title {external_id}",
        document_type="8-K",
        url=f"https://example.test/{external_id}",
        collected_at=datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc),
        raw_metadata=metadata,
        market=market,
        effective_at=effective_at,
    )


class DailyResearchScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.project_root = Path(self.temporary_directory.name)
        (self.project_root / "config").mkdir()
        (self.project_root / "data").mkdir()
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\n  - news\n  - community\n"
            "database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        (self.project_root / "config" / "universe.csv").write_text(
            "ticker,list_type\nAAPL,holdings\n", encoding="utf-8"
        )
        cache_directory = self.project_root / ".cache" / "investment_monitor"
        cache_directory.mkdir(parents=True)
        (cache_directory / "company_tickers.json").write_text("{}", encoding="utf-8")
        self.items = SQLiteInformationRepository(self.project_root / "data" / "web.sqlite3")
        self.application = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
            clock=lambda: FIXED_NOW,
        )
        self.ai = FakeAI()
        self.application.research._settings = ResearchSettings(enabled=True, api_key="k")
        self.application.research._ai = self.ai

    def tearDown(self):
        self.application.research.shutdown()
        self.temporary_directory.cleanup()

    def noop_collection_runner(self, **kwargs):
        return ConfiguredCollectionResult(
            items=(),
            failures=(),
            save_result=SaveResult(),
            database_path=self.project_root / "data" / "web.sqlite3",
            stored_count=self.items.count(),
        )

    def payload(self, response):
        return json.loads(response.body.decode("utf-8"))

    def add_company(self, ticker, lists, market="us"):
        class R:
            def resolve(self, t):
                return {
                    "ticker": t.upper(),
                    "name": f"{t.upper()} Inc.",
                    "exchange": "X",
                    "cik": "",
                    "mapping_status": "mapped",
                }

        result = self.application.repository.add_companies_batch(
            ticker, tuple(lists), R(), market=market
        )
        self.assertFalse(result["failed"])

    def company_id(self, ticker, market="us"):
        for company in self.application.repository.companies():
            if company["ticker"] == ticker and company["market"] == market:
                return company["id"]
        raise AssertionError(f"company {ticker}/{market} not found")

    def daily_rows(self, company_id, list_slug=None, start=START, end=END):
        result = self.application.repository.daily_display_rows(list_slug, start, end)
        return [r for r in result.items if int(r["company_id"]) == company_id]

    def daily_ids(self, company_id, **kwargs):
        return [int(r["id"]) for r in self.daily_rows(company_id, **kwargs)]

    def daily_http_count(self, ticker, list_slug=None):
        url = f"/api/daily-range?{RANGE_QUERY}"
        if list_slug:
            url += f"&list={list_slug}"
        payload = self.payload(self.application.handle("GET", url))
        count = 0
        for day in payload["days"]:
            for company in day["companies"]:
                if company["ticker"] == ticker:
                    count += len(company["items"])
        return count

    def generate_and_wait(self, company_id, language="en", list_slug=None,
                          start="2026-08-10", end="2026-08-13", force=False):
        body = {
            "company_id": company_id,
            "language": language,
            "force": force,
            "start_date": start,
            "end_date": end,
        }
        if list_slug:
            body["list"] = list_slug
        result = self.payload(self.application.handle(
            "POST", "/api/research/generate",
            json.dumps(body).encode(),
            headers=SAME_ORIGIN_HEADERS,
        ))
        if result.get("status") == "generating":
            generation_id = result["generation_id"]
            for _ in range(200):
                status = self.payload(self.application.handle(
                    "GET", f"/api/research/generations/{generation_id}"
                ))
                if status["status"] != "generating":
                    return status
                time.sleep(0.02)
            return status
        return result

    def seed_mixed_evidence(self):
        """In-range and out-of-range items across all categories and rules."""
        self.items.save((
            # date-only filing aligned by calendar_date (stays on 08-12 even
            # though its timestamps would convert into 08-13 in Shanghai)
            make_item("filing-dateonly", calendar_date="2026-08-12",
                      published_at=datetime(2026, 8, 12, 17, 0, tzinfo=timezone.utc)),
            # timestamped filing with effective_at
            make_item("filing-eff", effective_at=datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc)),
            # news with effective_at near the Shanghai day boundary
            make_item("news-boundary", source="news", source_type="news",
                      effective_at=datetime(2026, 8, 12, 16, 30, tzinfo=timezone.utc)),
            # community item
            make_item("community-1", source="community", source_type="community"),
            # generated/mock item: never shown, never used
            make_item("generated-1", generated=True),
            # out-of-range item (before start)
            make_item("old-1", published_at=datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc)),
            # out-of-range item (after end, in Shanghai)
            make_item("future-1", source="news", source_type="news",
                      effective_at=datetime(2026, 8, 13, 17, 0, tzinfo=timezone.utc)),
        ))

    def test_daily_research_prompt_snapshot_are_identical(self):
        self.add_company("AAPL", ["holdings"])
        self.seed_mixed_evidence()
        aapl = self.company_id("AAPL")

        daily_ids = sorted(self.daily_ids(aapl))
        # The expected set: date-only filing, effective filing, boundary news,
        # community. Generated and out-of-range items are excluded.
        self.assertEqual(len(daily_ids), 4)

        selection = self.application.research._select(aapl, "en", SCOPE)
        candidate_ids = sorted(e.item_id for e in selection.evidence)
        self.assertEqual(daily_ids, candidate_ids)

        result = self.generate_and_wait(aapl)
        self.assertEqual(result["status"], "completed")
        card = self.payload(self.application.handle(
            "GET", f"/api/research/cards/{result['card_id']}"
        ))
        snapshot_ids = sorted(int(e["information_item_id"]) for e in card["evidence"])
        self.assertEqual(daily_ids, snapshot_ids)

        # The fake model received exactly the snapshot's refs, in order.
        prompt = self.ai.calls[0]["user"]
        refs = [e["evidence_ref"] for e in card["evidence"]]
        for ref in refs:
            self.assertIn(f"[{ref}]", prompt)
        self.assertEqual(prompt.count("[E"), len(refs))
        self.assertEqual(len(refs), len(daily_ids))

        # The public Daily payload shows the same count for the company.
        self.assertEqual(self.daily_http_count("AAPL"), len(daily_ids))

    def test_date_only_filing_day_attribution_matches_daily(self):
        self.add_company("AAPL", ["holdings"])
        # calendar_date 2026-08-10 but effective_at lands on 08-13 in Shanghai.
        self.items.save((
            make_item("filing-dateonly", calendar_date="2026-08-10",
                      effective_at=datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc)),
        ))
        aapl = self.company_id("AAPL")
        # In range for 08-10, out of range for 08-13, exactly like Daily.
        in_scope = self.daily_ids(aapl, start=date(2026, 8, 10), end=date(2026, 8, 10))
        out_scope = self.daily_ids(aapl, start=date(2026, 8, 13), end=date(2026, 8, 13))
        self.assertEqual(len(in_scope), 1)
        self.assertEqual(len(out_scope), 0)
        payload = self.payload(self.application.handle(
            "GET", "/api/daily-range?start_date=2026-08-10&end_date=2026-08-10"
        ))
        self.assertEqual(payload["days"][0]["item_count"], 1)

    def test_shanghai_boundary_matches_daily(self):
        self.add_company("AAPL", ["holdings"])
        self.items.save((
            make_item("before", source="news", source_type="news",
                      effective_at=datetime(2026, 8, 10, 15, 59, 59, tzinfo=timezone.utc)),
            make_item("after", source="news", source_type="news",
                      effective_at=datetime(2026, 8, 10, 16, 0, 0, tzinfo=timezone.utc)),
        ))
        aapl = self.company_id("AAPL")
        day10 = self.daily_ids(aapl, start=date(2026, 8, 10), end=date(2026, 8, 10))
        day11 = self.daily_ids(aapl, start=date(2026, 8, 11), end=date(2026, 8, 11))
        self.assertEqual(len(day10), 1)
        self.assertEqual(len(day11), 1)
        self.assertNotEqual(day10, day11)

    def test_strict_ticker_market_isolation(self):
        self.add_company("ABC", ["holdings"], market="us")
        self.add_company("ABC", ["holdings"], market="hk")
        self.items.save((
            make_item("abc-us", tickers=("ABC",), market="us", title="ABC US filing"),
            make_item("abc-hk", tickers=("ABC",), market="hk", title="ABC HK filing"),
        ))
        abc_us = self.company_id("ABC", "us")
        abc_hk = self.company_id("ABC", "hk")
        us_rows = self.daily_rows(abc_us)
        hk_rows = self.daily_rows(abc_hk)
        self.assertEqual([r["title"] for r in us_rows], ["ABC US filing"])
        self.assertEqual([r["title"] for r in hk_rows], ["ABC HK filing"])

    def test_multi_company_item_appears_for_each_company(self):
        self.add_company("AAPL", ["holdings"])
        self.add_company("MSFT", ["planned"])
        self.items.save((
            make_item("shared-1", tickers=("AAPL", "MSFT")),
        ))
        aapl = self.company_id("AAPL")
        msft = self.company_id("MSFT")
        self.assertEqual(len(self.daily_ids(aapl)), 1)
        self.assertEqual(len(self.daily_ids(msft)), 1)
        self.assertEqual(self.daily_ids(aapl), self.daily_ids(msft))

    def test_custom_list_only_company_not_in_research(self):
        custom = self.application.repository.create_list("My Custom")
        self.add_company("TSLA", [custom["slug"]])
        self.seed_mixed_evidence()
        # Default scope: a company only in a custom list never appears.
        payload = self.payload(self.application.handle(
            "GET", f"/api/research/companies?{RANGE_QUERY}"
        ))
        self.assertNotIn("TSLA", {c["ticker"] for c in payload["companies"]})
        # A custom slug is rejected as a Research scope entry (spec: only
        # holdings / planned / watchlist are valid Research list scopes).
        response = self.application.handle(
            "GET", f"/api/research/companies?{RANGE_QUERY}&list={custom['slug']}"
        )
        self.assertEqual(response.status, 400)

    def test_list_scope_filters_rows_like_daily(self):
        self.add_company("AAPL", ["holdings"])
        self.add_company("MSFT", ["planned"])
        self.items.save((
            make_item("aapl-1"),
            make_item("msft-1", tickers=("MSFT",)),
        ))
        aapl = self.company_id("AAPL")
        # Holdings scope: AAPL rows are the same as Daily with list=holdings.
        rows = self.daily_rows(aapl, list_slug="holdings")
        self.assertEqual(len(rows), 1)
        payload = self.payload(self.application.handle(
            "GET", f"/api/daily-range?{RANGE_QUERY}&list=holdings"
        ))
        tickers = {
            c["ticker"] for d in payload["days"] for c in d["companies"]
        }
        self.assertEqual(tickers, {"AAPL"})

    def test_soft_dedupe_does_not_change_row_counts(self):
        self.add_company("AAPL", ["holdings"])
        # Two near-identical cross-source items: soft dedupe may annotate but
        # must never delete a row on either side.
        self.items.save((
            make_item("dedupe-a", source="news", source_type="news",
                      title="Same event reported"),
            make_item("dedupe-b", source="community", source_type="community",
                      title="Same event reported"),
        ))
        aapl = self.company_id("AAPL")
        self.assertEqual(len(self.daily_ids(aapl)), 2)
        selection = self.application.research._select(aapl, "en", SCOPE)
        self.assertEqual(selection.total, 2)

    def test_31_items_flow_through_untruncated(self):
        self._assert_full_flow(31)

    def test_150_items_flow_through_untruncated(self):
        self._assert_full_flow(150)

    def _assert_full_flow(self, count):
        self.add_company("AAPL", ["holdings"])
        self.items.save(tuple(
            make_item(f"bulk-{i}", effective_at=datetime(
                2026, 8, 10 + (i % 4), (i % 12), tzinfo=timezone.utc
            ))
            for i in range(count)
        ))
        aapl = self.company_id("AAPL")
        daily_ids = sorted(self.daily_ids(aapl))
        self.assertEqual(len(daily_ids), count)

        selection = self.application.research._select(aapl, "en", SCOPE)
        self.assertEqual(selection.total, count)
        self.assertEqual(sorted(e.item_id for e in selection.evidence), daily_ids)

        result = self.generate_and_wait(aapl)
        self.assertEqual(result["status"], "completed")
        card = self.payload(self.application.handle(
            "GET", f"/api/research/cards/{result['card_id']}"
        ))
        self.assertEqual(len(card["evidence"]), count)
        self.assertEqual(
            sorted(int(e["information_item_id"]) for e in card["evidence"]),
            daily_ids,
        )
        self.assertEqual(self.ai.calls[0]["user"].count("[E"), count)

    def test_max_items_env_has_no_effect(self):
        with patch.dict("os.environ", {"RESEARCH_MAX_EVIDENCE_ITEMS": "5"}):
            settings = ResearchSettings.from_environment()
        self.assertFalse(hasattr(settings, "max_evidence_items"))
        self._assert_full_flow(31)

    def test_range_too_large_fails_honestly(self):
        self.add_company("AAPL", ["holdings"])
        self.items.save(tuple(
            make_item(f"big-{i}", title="标题" * 100,
                      effective_at=datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc))
            for i in range(10)
        ))
        aapl = self.company_id("AAPL")
        import investment_monitor.research as research_mod
        with patch.object(research_mod, "MAX_PROMPT_BYTES", 200):
            result = self.generate_and_wait(aapl)
        self.assertEqual(result.get("code"), "research_range_too_large")
        self.assertEqual(result.get("error_code") in (None, "research_range_too_large"), True)
        self.assertEqual(len(self.ai.calls), 0)
        # No generating/completed card, no partial snapshot.
        scoped = self.application.research._repo.latest_card(aapl, "en", SCOPE)
        self.assertIsNone(scoped)
        # Narrowing the range to an empty day reports insufficient evidence,
        # not a model error.
        empty = self.generate_and_wait(aapl, start="2026-08-13", end="2026-08-13")
        self.assertEqual(empty.get("code"), "no_eligible_evidence")

    def test_range_too_large_message_not_invalid_model_response(self):
        self.add_company("AAPL", ["holdings"])
        self.items.save(tuple(
            make_item(f"big-{i}", title="标题" * 100)
            for i in range(10)
        ))
        aapl = self.company_id("AAPL")
        import investment_monitor.research as research_mod
        with patch.object(research_mod, "MAX_PROMPT_BYTES", 200):
            result = self.generate_and_wait(aapl)
        self.assertNotEqual(result.get("code"), "invalid_model_response")
        self.assertNotEqual(result.get("error_code"), "invalid_model_response")


class ResearchScopeApiTests(unittest.TestCase):
    """URL/validation/cache/stale semantics of the scoped Research APIs."""

    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.project_root = Path(self.temporary_directory.name)
        (self.project_root / "config").mkdir()
        (self.project_root / "data").mkdir()
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\n  - news\n  - community\n"
            "database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        (self.project_root / "config" / "universe.csv").write_text(
            "ticker,list_type\nAAPL,holdings\n", encoding="utf-8"
        )
        cache_directory = self.project_root / ".cache" / "investment_monitor"
        cache_directory.mkdir(parents=True)
        (cache_directory / "company_tickers.json").write_text("{}", encoding="utf-8")
        self.items = SQLiteInformationRepository(self.project_root / "data" / "web.sqlite3")
        self.application = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
            clock=lambda: FIXED_NOW,
        )
        self.ai = FakeAI()
        self.application.research._settings = ResearchSettings(enabled=True, api_key="k")
        self.application.research._ai = self.ai

    def tearDown(self):
        self.application.research.shutdown()
        self.temporary_directory.cleanup()

    def noop_collection_runner(self, **kwargs):
        return ConfiguredCollectionResult(
            items=(),
            failures=(),
            save_result=SaveResult(),
            database_path=self.project_root / "data" / "web.sqlite3",
            stored_count=self.items.count(),
        )

    def payload(self, response):
        return json.loads(response.body.decode("utf-8"))

    def add_aapl(self):
        class R:
            def resolve(self, t):
                return {
                    "ticker": "AAPL", "name": "Apple Inc.", "exchange": "Nasdaq",
                    "cik": "", "mapping_status": "mapped",
                }

        result = self.application.repository.add_companies_batch(
            "AAPL", ("holdings",), R()
        )
        self.assertFalse(result["failed"])
        return self.application.repository.companies()[0]["id"]

    def seed(self, count=3, day=11):
        self.items.save(tuple(
            make_item(f"s-{day}-{i}", effective_at=datetime(
                2026, 8, day, i % 23, tzinfo=timezone.utc
            ))
            for i in range(count)
        ))

    def generate_and_wait(self, company_id, start, end, force=False, list_slug=None):
        body = {
            "company_id": company_id, "language": "en", "force": force,
            "start_date": start, "end_date": end,
        }
        if list_slug:
            body["list"] = list_slug
        result = self.payload(self.application.handle(
            "POST", "/api/research/generate",
            json.dumps(body).encode(), headers=SAME_ORIGIN_HEADERS,
        ))
        if result.get("status") == "generating":
            generation_id = result["generation_id"]
            for _ in range(200):
                status = self.payload(self.application.handle(
                    "GET", f"/api/research/generations/{generation_id}"
                ))
                if status["status"] != "generating":
                    return status
                time.sleep(0.02)
            return status
        return result

    # --- validation ---

    def test_companies_start_after_end_is_400(self):
        response = self.application.handle(
            "GET", "/api/research/companies?start_date=2026-08-13&end_date=2026-08-10"
        )
        self.assertEqual(response.status, 400)

    def test_companies_invalid_date_is_400(self):
        response = self.application.handle(
            "GET", "/api/research/companies?start_date=not-a-date"
        )
        self.assertEqual(response.status, 400)

    def test_companies_invalid_list_is_400(self):
        response = self.application.handle(
            "GET", f"/api/research/companies?{RANGE_QUERY}&list=custom-x"
        )
        self.assertEqual(response.status, 400)

    def test_generate_start_after_end_is_400(self):
        aapl = self.add_aapl()
        response = self.application.handle(
            "POST", "/api/research/generate",
            json.dumps({
                "company_id": aapl, "language": "en",
                "start_date": "2026-08-13", "end_date": "2026-08-10",
            }).encode(),
            headers=SAME_ORIGIN_HEADERS,
        )
        self.assertEqual(response.status, 400)

    def test_generate_invalid_list_is_400(self):
        aapl = self.add_aapl()
        response = self.application.handle(
            "POST", "/api/research/generate",
            json.dumps({
                "company_id": aapl, "language": "en",
                "start_date": "2026-08-10", "end_date": "2026-08-13",
                "list": "custom-x",
            }).encode(),
            headers=SAME_ORIGIN_HEADERS,
        )
        self.assertEqual(response.status, 400)

    def test_generate_company_outside_selected_list_rejected(self):
        aapl = self.add_aapl()  # holdings only
        self.seed()
        result = self.generate_and_wait(
            aapl, "2026-08-10", "2026-08-13", list_slug="planned"
        )
        # The web layer turns the scope-membership failure into a 400.
        self.assertEqual(result.get("status"), None)
        self.assertIn("error", result)

    def test_default_range_is_current_shanghai_day(self):
        self.add_aapl()
        self.seed(3, day=13)
        payload = self.payload(self.application.handle(
            "GET", "/api/research/companies"
        ))
        self.assertEqual(payload["start_date"], "2026-08-13")
        self.assertEqual(payload["end_date"], "2026-08-13")
        self.assertEqual(payload["companies"][0]["evidence_total"], 3)

    def test_companies_counts_come_from_selected_range(self):
        aapl = self.add_aapl()
        self.seed(3, day=11)
        self.seed(5, day=1)  # out of range
        payload = self.payload(self.application.handle(
            "GET", f"/api/research/companies?{RANGE_QUERY}"
        ))
        company = payload["companies"][0]
        self.assertEqual(company["evidence_total"], 3)
        self.assertEqual(company["filing_count"], 3)

    # --- cache, stale, range isolation ---

    def test_cache_hit_same_scope_and_stale_on_new_in_range_evidence(self):
        aapl = self.add_aapl()
        self.seed(3)
        first = self.generate_and_wait(aapl, "2026-08-10", "2026-08-13")
        self.assertEqual(first["status"], "completed")
        second = self.generate_and_wait(aapl, "2026-08-10", "2026-08-13")
        self.assertEqual(second["status"], "cached")
        self.assertEqual(len(self.ai.calls), 1)
        # New evidence inside the range makes the card stale.
        self.seed(1, day=12)
        payload = self.payload(self.application.handle(
            "GET", f"/api/research/companies?{RANGE_QUERY}"
        ))
        self.assertEqual(payload["companies"][0]["status"], "stale")

    def test_out_of_range_evidence_does_not_stale_card(self):
        aapl = self.add_aapl()
        self.seed(3)
        first = self.generate_and_wait(aapl, "2026-08-10", "2026-08-13")
        self.assertEqual(first["status"], "completed")
        self.seed(2, day=1)  # outside the range
        payload = self.payload(self.application.handle(
            "GET", f"/api/research/companies?{RANGE_QUERY}"
        ))
        self.assertEqual(payload["companies"][0]["status"], "cached")

    def test_card_from_range_a_never_shows_for_range_b(self):
        aapl = self.add_aapl()
        self.seed(3, day=11)
        first = self.generate_and_wait(aapl, "2026-08-10", "2026-08-13")
        self.assertEqual(first["status"], "completed")
        # Range B (only 08-13, no evidence): no card, no latest_card_id.
        payload = self.payload(self.application.handle(
            "GET", "/api/research/companies?start_date=2026-08-13&end_date=2026-08-13"
        ))
        company = payload["companies"][0]
        self.assertIsNone(company["latest_card_id"])
        self.assertEqual(company["status"], "insufficient_evidence")

    def test_cards_for_different_ranges_coexist(self):
        aapl = self.add_aapl()
        self.seed(3, day=11)
        self.seed(3, day=13)
        first = self.generate_and_wait(aapl, "2026-08-10", "2026-08-12")
        second = self.generate_and_wait(aapl, "2026-08-13", "2026-08-13")
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "completed")
        self.assertNotEqual(first["card_id"], second["card_id"])
        card_a = self.payload(self.application.handle(
            "GET", f"/api/research/cards/{first['card_id']}"
        ))
        card_b = self.payload(self.application.handle(
            "GET", f"/api/research/cards/{second['card_id']}"
        ))
        self.assertEqual(card_a["start_date"], "2026-08-10")
        self.assertEqual(card_a["end_date"], "2026-08-12")
        self.assertEqual(card_a["evidence_total"], 3)
        self.assertEqual(card_a["evidence_sent"], 3)
        self.assertEqual(card_b["evidence_total"], 3)

    def test_legacy_unscoped_card_never_impersonates_scoped_card(self):
        aapl = self.add_aapl()
        self.seed(3)
        # Simulate a legacy card created before range columns existed.
        repo = self.application.research._repo
        legacy_id = repo.create_generation(
            company_id=aapl, language="en", evidence_fingerprint="legacy",
            model_provider_fingerprint="p", model_name="m",
        )
        repo.complete_generation(
            legacy_id, company_id=aapl, content_json="{}", evidence=(),
        )
        payload = self.payload(self.application.handle(
            "GET", f"/api/research/companies?{RANGE_QUERY}"
        ))
        company = payload["companies"][0]
        self.assertIsNone(company["latest_card_id"])
        self.assertEqual(company["status"], "not_generated")

    def test_community_only_range_never_calls_model(self):
        aapl = self.add_aapl()
        self.items.save(tuple(
            make_item(f"c-{i}", source="community", source_type="community")
            for i in range(5)
        ))
        result = self.generate_and_wait(aapl, "2026-08-10", "2026-08-13")
        self.assertEqual(result["code"], "insufficient_evidence")
        self.assertEqual(len(self.ai.calls), 0)

    def test_frontend_range_controls_and_state_tokens(self):
        js = (
            Path(__file__).resolve().parent.parent
            / "src" / "investment_monitor" / "web_static" / "app.js"
        ).read_text(encoding="utf-8")
        for token in (
            "research-start-date",
            "research-end-date",
            "research-list",
            "research.from",
            "research.to",
            "research.start_after_end",
            "research.card_scope",
            "research.evidence_in_range",
            "research.evidence_sent",
            "research.no_card_for_range",
            "currentResearchScope",
            "start_date: scope.startDate",
            "end_date: scope.endDate",
            "report_selected_date",
            'params.get("date")',  # legacy date= compatibility, like Daily
        ):
            self.assertIn(token, js)
        # Range switches navigate (full reload), so a previous range's card is
        # never rendered under a new scope.
        self.assertIn("location.href = `/research?${next}`", js)


if __name__ == "__main__":
    unittest.main()
