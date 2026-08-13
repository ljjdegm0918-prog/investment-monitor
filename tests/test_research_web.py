import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from investment_monitor.application import ConfiguredCollectionResult
from investment_monitor.models import InformationItem
from investment_monitor.repository import SaveResult
from investment_monitor.research import ResearchSettings
from investment_monitor.sqlite_repository import SQLiteInformationRepository
from investment_monitor.web import WebApplication


APP_JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "investment_monitor"
    / "web_static"
    / "app.js"
)

APP_CSS_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "investment_monitor"
    / "web_static"
    / "app.css"
)

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


SAME_ORIGIN_HEADERS = {
    "Content-Type": "application/json",
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
}

# Explicit range covering every seeded fixture date (2026-01), so tests do not
# depend on the real clock (the default range is the current Shanghai day).
RANGE_START = "2025-06-01"
RANGE_END = "2027-01-01"
RANGE_QUERY = f"?start_date={RANGE_START}&end_date={RANGE_END}"


class FakeAI:
    def __init__(self, card=None, delay=0.0):
        self.card = card or DEFAULT_CARD
        self.delay = delay
        self.calls = []

    def generate(self, *, system_prompt, user_prompt, language):
        self.calls.append(language)
        if self.delay:
            time.sleep(self.delay)
        return self.card


class ResearchWebTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.project_root = Path(self.temporary_directory.name)
        (self.project_root / "config").mkdir()
        (self.project_root / "data").mkdir()
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\ndatabase_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        (self.project_root / "config" / "universe.csv").write_text(
            "ticker,list_type\nAAPL,holdings\n", encoding="utf-8"
        )
        cache_directory = self.project_root / ".cache" / "investment_monitor"
        cache_directory.mkdir(parents=True)
        (cache_directory / "company_tickers.json").write_text(json.dumps({
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corporation"},
        }), encoding="utf-8")
        self.items = SQLiteInformationRepository(self.project_root / "data" / "web.sqlite3")
        self.application = WebApplication(
            self.project_root, collection_runner=self.noop_collection_runner
        )

    def tearDown(self):
        self.application.research.shutdown()
        self.temporary_directory.cleanup()

    def payload(self, response):
        return json.loads(response.body.decode("utf-8"))

    def noop_collection_runner(self, **kwargs):
        return ConfiguredCollectionResult(
            items=(),
            failures=(),
            save_result=SaveResult(),
            database_path=self.project_root / "data" / "web.sqlite3",
            stored_count=self.items.count(),
        )

    def seed_evidence(self, count=3):
        for i in range(count):
            self.items.save((InformationItem(
                source="sec",
                source_type="regulatory_filing",
                external_id=f"research-{i}",
                tickers=("AAPL",),
                issuer="Apple Inc.",
                published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                title=f"Apple filing {i}",
                document_type="8-K",
                url=f"https://www.sec.gov/Archives/research-{i}.htm",
                collected_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                raw_metadata={"acceptanceDateTime": "2026-01-01T11:00:00-04:00"},
            ),))

    def aapl_id(self):
        return [c for c in self.application.repository.companies() if c["ticker"] == "AAPL"][0]["id"]

    def enable_research(self, ai=None):
        self.application.research._settings = ResearchSettings(
            enabled=True, api_key="test-key"
        )
        if ai is not None:
            self.application.research._ai = ai

    def generate_and_wait(self, company_id, language="en", force=False):
        result = self.payload(self.application.handle(
            "POST", "/api/research/generate",
            json.dumps({
                "company_id": company_id, "language": language, "force": force,
                "start_date": RANGE_START, "end_date": RANGE_END,
            }).encode(),
            headers=SAME_ORIGIN_HEADERS,
        ))
        if result.get("status") == "generating":
            generation_id = result["generation_id"]
            for _ in range(100):
                status = self.payload(self.application.handle(
                    "GET", f"/api/research/generations/{generation_id}"
                ))
                if status["status"] != "generating":
                    return status
                time.sleep(0.05)
            return status
        return result

    # --- page and static ---

    def test_research_page_served(self):
        page = self.application.handle("GET", "/research")
        self.assertEqual(page.status, 200)
        self.assertIn(b'data-view="research"', page.body)

    def test_app_js_has_research_nav_and_disclaimer(self):
        js = APP_JS_PATH.read_text(encoding="utf-8")
        for token in (
            "nav.research",
            "renderResearch",
            "researchCardContent",
            "research.disclaimer",
            "Research assistance only. This is not investment advice.",
            "仅供研究辅助，不构成投资建议。",
            "safeUrl(item.url_snapshot)",
            "researchEvidenceList",
        ):
            self.assertIn(token, js)

    def test_app_js_escapes_model_content(self):
        js = APP_JS_PATH.read_text(encoding="utf-8")
        # Card content is rendered through esc(), never raw innerHTML of model text.
        self.assertIn("esc(c.title)", js)
        self.assertIn("esc(c.summary)", js)
        self.assertIn("esc(r.explanation)", js)
        self.assertIn("esc(d.why_it_matters)", js)

    def test_app_js_research_print_button_and_metadata(self):
        js = APP_JS_PATH.read_text(encoding="utf-8")
        for token in (
            "research.print_pdf",
            "research.print_title",
            'data-action="print-research"',
            "window.print()",
            "beforeprint",
            "researchCompanyLine",
            "researchInfoTypeLabel",
            "data-card-id",
            "Print / Save PDF",
            "打印 / 保存 PDF",
        ):
            self.assertIn(token, js)
        # Card metadata comes from the server payload fields (company, counts),
        # never re-queried from the current page.
        for token in (
            "card.company_name",
            "card.ticker",
            "card.market",
            "card.filing_count",
            "card.news_count",
            "card.community_count",
        ):
            self.assertIn(token, js)

    def test_app_js_requires_completed_status_for_print(self):
        js = APP_JS_PATH.read_text(encoding="utf-8")
        # Both viewCard and researchCardContent gate on completed status, so a
        # failed or generating card never renders the print action and never
        # reaches bindResearchPrint / window.print().
        self.assertIn('card.status !== "completed"', js)
        self.assertIn("bindResearchPrint", js)

    def test_app_css_research_print_rules(self):
        css = APP_CSS_PATH.read_text(encoding="utf-8")
        for token in (
            "@media print",
            ".page-heading",
            "#research-companies",
            ".research-card .button",
            ".research-card-title .button",
            ".print-brand",
            ".research-claims li",
            ".evidence-list .raw-url",
            "overflow-wrap:anywhere",
        ):
            self.assertIn(token, css)

    def test_app_js_generation_state_machine(self):
        js = APP_JS_PATH.read_text(encoding="utf-8")
        # Foreground polling uses an explicit timeout, not a fake failure.
        self.assertIn("GENERATION_FOREGROUND_TIMEOUT_MS", js)
        self.assertIn("GENERATION_POLL_INTERVAL_MS", js)
        self.assertIn("research.generating_in_background", js)
        self.assertIn("generationFailureMessage", js)
        self.assertIn("research.error.invalid_response", js)
        # pollGeneration must not hardcode 120 attempts or toast a fake failure
        # on the foreground timeout path.
        self.assertNotIn("attempt < 120", js)
        # generateCard must re-sync from the server in a finally block.
        self.assertIn("finally {", js)

    # --- companies listing ---

    def test_companies_listing_and_filter(self):
        self.application.handle(
            "POST", "/api/companies/batch",
            json.dumps({"tickers": "MSFT", "lists": ["planned"], "market": "us"}).encode(),
            headers=SAME_ORIGIN_HEADERS,
        )
        data = self.payload(self.application.handle("GET", "/api/research/companies" + RANGE_QUERY))
        tickers = {c["ticker"] for c in data["companies"]}
        self.assertIn("AAPL", tickers)
        self.assertIn("MSFT", tickers)
        holdings = self.payload(self.application.handle(
            "GET", f"/api/research/companies?list=holdings&start_date={RANGE_START}&end_date={RANGE_END}"
        ))
        self.assertEqual([c["ticker"] for c in holdings["companies"]], ["AAPL"])

    def test_unknown_list_rejected(self):
        response = self.application.handle(
            "GET", "/api/research/companies?list=does-not-exist"
        )
        self.assertEqual(response.status, 400)

    def test_model_status_is_honest_by_default(self):
        data = self.payload(self.application.handle("GET", "/api/research/model"))
        self.assertFalse(data["model"]["enabled"])
        self.assertFalse(data["model"]["configured"])

    def test_insufficient_evidence_status(self):
        self.enable_research()
        data = self.payload(self.application.handle("GET", "/api/research/companies" + RANGE_QUERY))
        aapl = [c for c in data["companies"] if c["ticker"] == "AAPL"][0]
        self.assertEqual(aapl["status"], "insufficient_evidence")

    def test_model_not_configured_status(self):
        data = self.payload(self.application.handle("GET", "/api/research/companies" + RANGE_QUERY))
        aapl = [c for c in data["companies"] if c["ticker"] == "AAPL"][0]
        self.assertEqual(aapl["status"], "model_not_configured")

    # --- generation ---

    def test_generate_disabled_by_default(self):
        self.seed_evidence()
        result = self.payload(self.application.handle(
            "POST", "/api/research/generate",
            json.dumps({"company_id": self.aapl_id(), "language": "en", "force": False, "start_date": RANGE_START, "end_date": RANGE_END}).encode(),
            headers=SAME_ORIGIN_HEADERS,
        ))
        self.assertEqual(result["code"], "research_disabled")

    def test_generate_rejects_unknown_company(self):
        self.enable_research()
        response = self.application.handle(
            "POST", "/api/research/generate",
            json.dumps({"company_id": 99999, "language": "en", "force": False, "start_date": RANGE_START, "end_date": RANGE_END}).encode(),
            headers=SAME_ORIGIN_HEADERS,
        )
        self.assertEqual(response.status, 400)

    def test_generate_rejects_illegal_language(self):
        self.enable_research()
        self.seed_evidence()
        response = self.application.handle(
            "POST", "/api/research/generate",
            json.dumps({"company_id": self.aapl_id(), "language": "fr", "force": False, "start_date": RANGE_START, "end_date": RANGE_END}).encode(),
            headers=SAME_ORIGIN_HEADERS,
        )
        self.assertEqual(response.status, 400)

    def _force_body(self, force_value, include=True):
        payload = {"company_id": self.aapl_id(), "language": "en", "start_date": RANGE_START, "end_date": RANGE_END}
        if include:
            payload["force"] = force_value
        return json.dumps(payload).encode()

    def test_force_rejects_string_true(self):
        self.enable_research()
        resp = self.application.handle(
            "POST", "/api/research/generate", self._force_body("true"),
            headers=SAME_ORIGIN_HEADERS,
        )
        self.assertEqual(resp.status, 400)

    def test_force_rejects_string_false(self):
        self.enable_research()
        resp = self.application.handle(
            "POST", "/api/research/generate", self._force_body("false"),
            headers=SAME_ORIGIN_HEADERS,
        )
        self.assertEqual(resp.status, 400)

    def test_force_rejects_number_one(self):
        self.enable_research()
        resp = self.application.handle(
            "POST", "/api/research/generate", self._force_body(1),
            headers=SAME_ORIGIN_HEADERS,
        )
        self.assertEqual(resp.status, 400)

    def test_force_rejects_number_zero(self):
        self.enable_research()
        resp = self.application.handle(
            "POST", "/api/research/generate", self._force_body(0),
            headers=SAME_ORIGIN_HEADERS,
        )
        self.assertEqual(resp.status, 400)

    def test_force_rejects_null(self):
        self.enable_research()
        resp = self.application.handle(
            "POST", "/api/research/generate", self._force_body(None),
            headers=SAME_ORIGIN_HEADERS,
        )
        self.assertEqual(resp.status, 400)

    def test_force_missing_defaults_false(self):
        ai = FakeAI()
        self.enable_research(ai)
        self.seed_evidence()
        first = self.generate_and_wait(self.aapl_id())  # no force key -> default False
        self.assertEqual(first["status"], "completed")
        second = self.generate_and_wait(self.aapl_id())
        self.assertEqual(second["status"], "cached")  # default False hits cache
        self.assertEqual(len(ai.calls), 1)

    def test_generate_success_and_card_evidence_consistency(self):
        ai = FakeAI()
        self.enable_research(ai)
        self.seed_evidence()
        result = self.generate_and_wait(self.aapl_id())
        self.assertEqual(result["status"], "completed")
        card = self.payload(self.application.handle(
            "GET", f"/api/research/cards/{result['card_id']}"
        ))
        self.assertEqual(card["status"], "completed")
        # Evidence references in the card map to the stored snapshot.
        refs = {e["evidence_ref"] for e in card["evidence"]}
        self.assertEqual(refs, {"E1", "E2", "E3"})
        used = set()
        for change in card["content"]["recent_changes"]:
            used.update(change["evidence_ids"])
        self.assertTrue(used.issubset(refs))

    def test_card_payload_includes_company_identity_and_category_counts(self):
        ai = FakeAI()
        self.enable_research(ai)
        self.seed_evidence()
        result = self.generate_and_wait(self.aapl_id())
        self.assertEqual(result["status"], "completed")
        card = self.payload(self.application.handle(
            "GET", f"/api/research/cards/{result['card_id']}"
        ))
        # Print metadata must come from the frozen card snapshot, including the
        # company identity and per-category counts, without another query.
        # The universe import has no SEC rows yet, so the company name falls
        # back to the ticker; the field must still be present and truthful.
        self.assertEqual(card["company_name"], "AAPL")
        self.assertEqual(card["ticker"], "AAPL")
        self.assertEqual(card["market"], "us")
        self.assertEqual(card["filing_count"], 3)
        self.assertEqual(card["news_count"], 0)
        self.assertEqual(card["community_count"], 0)
        self.assertEqual(card["evidence_total"], 3)
        self.assertEqual(card["evidence_sent"], 3)
        self.assertEqual(card["start_date"], RANGE_START)
        self.assertEqual(card["end_date"], RANGE_END)

    def _create_card_in_status(self, status):
        """Create an AAPL card row in the given status via the repository."""
        repo = self.application.research._repo
        card_id = repo.create_generation(
            company_id=self.aapl_id(),
            language="en",
            evidence_fingerprint="fp",
            model_provider_fingerprint="provider",
            model_name="model",
        )
        if status == "failed":
            repo.fail_generation(card_id, "test_error")
        return card_id

    def _update_company_identity(self, company_id, *, name, ticker, market):
        with self.application.repository._connect() as connection:
            connection.execute(
                "UPDATE companies SET name = ?, ticker = ?, market = ? WHERE id = ?",
                (name, ticker, market, company_id),
            )

    def test_card_endpoint_rejects_non_completed_cards(self):
        # Only completed cards are printable. Failed and generating cards must
        # return a stable, content-free 404 and never expose their body/error.
        generating_id = self._create_card_in_status("generating")
        response = self.application.handle(
            "GET", f"/api/research/cards/{generating_id}"
        )
        self.assertEqual(response.status, 404)
        self.assertEqual(self.payload(response), {"error": "Card not found"})

        failed_id = self._create_card_in_status("failed")
        response = self.application.handle(
            "GET", f"/api/research/cards/{failed_id}"
        )
        self.assertEqual(response.status, 404)
        body = self.payload(response)
        self.assertEqual(body, {"error": "Card not found"})
        self.assertNotIn("test_error", json.dumps(body))

    def test_card_identity_is_frozen_snapshot(self):
        ai = FakeAI()
        self.enable_research(ai)
        self.seed_evidence()
        result = self.generate_and_wait(self.aapl_id())
        self.assertEqual(result["status"], "completed")
        card_id = result["card_id"]
        # Mutate the company identity after generation; the card payload must
        # still report the frozen snapshot, not the current identity.
        self._update_company_identity(
            self.aapl_id(), name="Renamed Corp", ticker="RNM", market="jp"
        )
        card = self.payload(self.application.handle(
            "GET", f"/api/research/cards/{card_id}"
        ))
        self.assertEqual(card["company_name"], "AAPL")
        self.assertEqual(card["ticker"], "AAPL")
        self.assertEqual(card["market"], "us")

    def test_legacy_card_without_snapshot_falls_back_to_current_identity(self):
        repo = self.application.research._repo
        company_id = self.aapl_id()
        # A legacy completed card (snapshot columns NULL) predates the
        # migration; it may fall back to the current identity.
        card_id = repo.create_generation(
            company_id=company_id,
            language="en",
            evidence_fingerprint="fp",
            model_provider_fingerprint="provider",
            model_name="model",
        )
        repo.complete_generation(
            card_id,
            company_id=company_id,
            content_json=json.dumps(DEFAULT_CARD),
            evidence=[],
        )
        self._update_company_identity(
            company_id, name="Renamed Corp", ticker="RNM", market="jp"
        )
        card = self.payload(self.application.handle(
            "GET", f"/api/research/cards/{card_id}"
        ))
        self.assertEqual(card["status"], "completed")
        self.assertEqual(card["company_name"], "Renamed Corp")
        self.assertEqual(card["ticker"], "RNM")
        self.assertEqual(card["market"], "jp")

    def test_generate_cache_hit_does_not_call_model(self):
        ai = FakeAI()
        self.enable_research(ai)
        self.seed_evidence()
        first = self.generate_and_wait(self.aapl_id())
        self.assertEqual(first["status"], "completed")
        self.assertEqual(len(ai.calls), 1)
        second = self.generate_and_wait(self.aapl_id())
        self.assertEqual(second["status"], "cached")
        self.assertEqual(len(ai.calls), 1)

    def test_regenerate_bypasses_cache(self):
        ai = FakeAI()
        self.enable_research(ai)
        self.seed_evidence()
        first = self.generate_and_wait(self.aapl_id())
        self.assertEqual(first["status"], "completed")
        second = self.generate_and_wait(self.aapl_id(), force=True)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(len(ai.calls), 2)

    def test_concurrent_duplicate_generation_blocked(self):
        ai = FakeAI(delay=0.5)
        self.enable_research(ai)
        self.seed_evidence()
        first = self.payload(self.application.handle(
            "POST", "/api/research/generate",
            json.dumps({"company_id": self.aapl_id(), "language": "en", "force": True, "start_date": RANGE_START, "end_date": RANGE_END}).encode(),
            headers=SAME_ORIGIN_HEADERS,
        ))
        self.assertEqual(first["status"], "generating")
        second = self.payload(self.application.handle(
            "POST", "/api/research/generate",
            json.dumps({"company_id": self.aapl_id(), "language": "en", "force": True, "start_date": RANGE_START, "end_date": RANGE_END}).encode(),
            headers=SAME_ORIGIN_HEADERS,
        ))
        self.assertEqual(second["code"], "generation_in_progress")

    def _generate_body(self, force=False):
        return json.dumps({"company_id": self.aapl_id(), "language": "en", "force": force}).encode()

    def test_csrf_cross_origin_origin_rejected(self):
        headers = dict(SAME_ORIGIN_HEADERS, Origin="https://evil.example.com")
        resp = self.application.handle(
            "POST", "/api/research/generate", self._generate_body(), headers=headers
        )
        self.assertEqual(resp.status, 403)
        self.assertIn("research_csrf_rejected", resp.body.decode("utf-8"))

    def test_csrf_cross_origin_referer_rejected(self):
        headers = {
            "Content-Type": "application/json",
            "Host": "127.0.0.1:8765",
            "Referer": "https://evil.example.com/x",
        }
        resp = self.application.handle(
            "POST", "/api/research/generate", self._generate_body(), headers=headers
        )
        self.assertEqual(resp.status, 403)

    def test_csrf_missing_origin_and_referer_rejected(self):
        headers = {"Content-Type": "application/json", "Host": "127.0.0.1:8765"}
        resp = self.application.handle(
            "POST", "/api/research/generate", self._generate_body(), headers=headers
        )
        self.assertEqual(resp.status, 403)

    def test_csrf_same_origin_allowed(self):
        resp = self.application.handle(
            "POST", "/api/research/generate", self._generate_body(),
            headers=SAME_ORIGIN_HEADERS,
        )
        self.assertEqual(resp.status, 200)
        self.assertIn("research_disabled", resp.body.decode("utf-8"))

    def test_csrf_text_plain_rejected_even_with_json_body(self):
        headers = {
            "Content-Type": "text/plain",
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
        }
        resp = self.application.handle(
            "POST", "/api/research/generate", self._generate_body(), headers=headers
        )
        self.assertEqual(resp.status, 403)

    def test_csrf_force_true_still_protected(self):
        headers = dict(SAME_ORIGIN_HEADERS, Origin="https://evil.example.com")
        resp = self.application.handle(
            "POST", "/api/research/generate", self._generate_body(force=True),
            headers=headers,
        )
        self.assertEqual(resp.status, 403)

    def test_csrf_same_hostname_different_port_rejected(self):
        headers = dict(SAME_ORIGIN_HEADERS, Origin="http://127.0.0.1:444")
        resp = self.application.handle(
            "POST", "/api/research/generate", self._generate_body(), headers=headers
        )
        self.assertEqual(resp.status, 403)

    def test_csrf_same_hostname_different_scheme_rejected(self):
        headers = dict(SAME_ORIGIN_HEADERS, Origin="https://127.0.0.1:8765")
        resp = self.application.handle(
            "POST", "/api/research/generate", self._generate_body(), headers=headers
        )
        self.assertEqual(resp.status, 403)

    def test_csrf_default_port_normalization(self):
        headers = {
            "Content-Type": "application/json",
            "Host": "example.com",
            "Origin": "http://example.com",
        }
        resp = self.application.handle(
            "POST", "/api/research/generate", self._generate_body(), headers=headers
        )
        self.assertEqual(resp.status, 200)  # passes CSRF, then disabled

        https_origin = {
            "Content-Type": "application/json",
            "Host": "example.com",
            "Origin": "https://example.com",
        }
        resp = self.application.handle(
            "POST", "/api/research/generate", self._generate_body(), headers=https_origin
        )
        self.assertEqual(resp.status, 403)  # https vs default http scheme

    def test_csrf_referer_fallback_checks_protocol_and_port(self):
        headers = {
            "Content-Type": "application/json",
            "Host": "127.0.0.1:8765",
            "Referer": "http://127.0.0.1:444/page",
        }
        resp = self.application.handle(
            "POST", "/api/research/generate", self._generate_body(), headers=headers
        )
        self.assertEqual(resp.status, 403)

    def test_csrf_spoofed_forwarded_proto_ignored(self):
        headers = dict(SAME_ORIGIN_HEADERS, Origin="https://127.0.0.1:8765")
        headers["X-Forwarded-Proto"] = "https"
        resp = self.application.handle(
            "POST", "/api/research/generate", self._generate_body(), headers=headers
        )
        self.assertEqual(resp.status, 403)

    def test_csrf_https_reverse_proxy_allows(self):
        with patch.dict("os.environ", {"WEB_EXTERNAL_SCHEME": "https"}):
            headers = {
                "Content-Type": "application/json",
                "Host": "115.159.81.177:9871",
                "Origin": "https://115.159.81.177:9871",
            }
            resp = self.application.handle(
                "POST", "/api/research/generate", self._generate_body(), headers=headers
            )
        self.assertEqual(resp.status, 200)  # passes CSRF, then disabled

    def test_csrf_https_reverse_proxy_different_port_rejected(self):
        with patch.dict("os.environ", {"WEB_EXTERNAL_SCHEME": "https"}):
            headers = {
                "Content-Type": "application/json",
                "Host": "115.159.81.177:9871",
                "Origin": "https://115.159.81.177:444",
            }
            resp = self.application.handle(
                "POST", "/api/research/generate", self._generate_body(), headers=headers
            )
        self.assertEqual(resp.status, 403)

    def test_csrf_https_reverse_proxy_different_scheme_rejected(self):
        with patch.dict("os.environ", {"WEB_EXTERNAL_SCHEME": "https"}):
            headers = {
                "Content-Type": "application/json",
                "Host": "115.159.81.177:9871",
                "Origin": "http://115.159.81.177:9871",
            }
            resp = self.application.handle(
                "POST", "/api/research/generate", self._generate_body(), headers=headers
            )
        self.assertEqual(resp.status, 403)

    def test_csrf_unconfigured_https_origin_rejected(self):
        # No WEB_EXTERNAL_SCHEME set (defaults to http), so an https Origin fails.
        headers = {
            "Content-Type": "application/json",
            "Host": "115.159.81.177:9871",
            "Origin": "https://115.159.81.177:9871",
        }
        resp = self.application.handle(
            "POST", "/api/research/generate", self._generate_body(), headers=headers
        )
        self.assertEqual(resp.status, 403)

    def test_stale_when_new_evidence_arrives(self):
        ai = FakeAI()
        self.enable_research(ai)
        self.seed_evidence(3)
        self.generate_and_wait(self.aapl_id())
        # Add a new item; the fingerprint changes and the card becomes stale.
        self.seed_evidence(1)
        self.items.save((InformationItem(
            source="sec", source_type="regulatory_filing",
            external_id="research-new", tickers=("AAPL",), issuer="Apple Inc.",
            published_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            title="Apple filing new", document_type="8-K",
            url="https://www.sec.gov/Archives/research-new.htm",
            collected_at=datetime(2026, 1, 6, tzinfo=timezone.utc),
            raw_metadata={"acceptanceDateTime": "2026-01-05T11:00:00-04:00"},
        ),))
        data = self.payload(self.application.handle("GET", "/api/research/companies" + RANGE_QUERY))
        aapl = [c for c in data["companies"] if c["ticker"] == "AAPL"][0]
        self.assertEqual(aapl["status"], "stale")

    # --- regression: existing endpoints still work ---

    def test_existing_endpoints_still_work(self):
        self.assertEqual(self.application.handle("GET", "/today").status, 200)
        self.assertEqual(self.application.handle("GET", "/api/feed").status, 200)
        daily = self.application.handle("GET", "/api/daily-range?start_date=2026-01-01&end_date=2026-01-02")
        self.assertEqual(daily.status, 200)
        sources = self.application.handle("GET", "/api/sources")
        self.assertEqual(sources.status, 200)

    def test_web_main_shutdown_closes_research_executor(self):
        from investment_monitor import web as web_mod

        app = MagicMock()
        app.research.shutdown.return_value = None
        server = MagicMock()
        server.serve_forever.side_effect = KeyboardInterrupt
        with patch.object(web_mod, "WebApplication", return_value=app), \
             patch.object(web_mod, "ThreadingHTTPServer", return_value=server), \
             patch.dict("os.environ", {"AUTO_DAILY_COLLECTION": "false"}):
            web_mod.main([])
        app.research.shutdown.assert_called_once()
        server.server_close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
