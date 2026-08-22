from datetime import date
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.sg_ir import (
    SgIrConnector, SgIrDataError, SgIrSource, SgIrUrlRule,
    builtin_sg_ir_sources, load_sources_from_path,
)
from investment_monitor.sources.sgx_announcements import (
    SgxAnnouncementConnector,
    SgxAnnouncementDiscovery,
)
from investment_monitor.dedupe import dedupe_key

FIXTURES = Path(__file__).parent / "fixtures" / "sg_ir"


def source(*, fmt="rss", adapter="article", pages=()):
    return SgIrSource(
        source_id="dbs-ir", ticker="D05.SI", issuer="DBS Group Holdings",
        exchange="SGX Mainboard", feed_url="https://investor.example.test/releases/feed",
        format=fmt, adapter=adapter, page_urls=pages,
        url_rules=(SgIrUrlRule("investor.example.test", "/"),),
        filing_terms=("financial results", "annual report"), issuer_type="reit",
        isin="SG1L01001701",
    )


def request(start=date(2026, 8, 18), end=date(2026, 8, 19)):
    return CollectionRequest(tickers=("D05",), start_date=start, end_date=end, markets={"D05": "sg"})


class SgIrTests(unittest.TestCase):
    def test_rss_classifies_filters_and_retains_provenance(self):
        body = (FIXTURES / "issuer_feed.xml").read_text()
        connector = SgIrConnector(sources=(source(),), fetcher=lambda url: body, rate_limit_seconds=0)
        result = connector.collect(request())
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(item.tickers, ("D05",))
        self.assertEqual(item.document_type, "financial_results")
        self.assertEqual(item.raw_metadata["source_tier"], 2)
        self.assertEqual(item.raw_metadata["issuer_type"], "reit")
        self.assertEqual(item.raw_metadata["attachment_urls"], ["https://investor.example.test/files/results-q2.pdf"])
        self.assertEqual(connector.last_collection_status, "partial")

    def test_html_hosted_template_and_singapore_date(self):
        body = (FIXTURES / "listedcompany.html").read_text()
        connector = SgIrConnector(sources=(source(fmt="html", adapter="listedcompany"),), fetcher=lambda url: body, rate_limit_seconds=0)
        result = connector.collect(request())
        self.assertEqual(result[0].document_type, "annual_report")
        self.assertEqual(result[0].published_at.astimezone().date(), date(2026, 8, 19))

    def test_builtin_singtel_datamodel_collects_real_template_without_config(self):
        body = (FIXTURES / "singtel_stock_exchange.html").read_text()
        connector = SgIrConnector(
            sources=builtin_sg_ir_sources(),
            fetcher=lambda _url: body,
            rate_limit_seconds=0,
        )
        result = connector.collect(CollectionRequest(
            tickers=("Z74.SI",),
            start_date=date(2026, 8, 18),
            end_date=date(2026, 8, 19),
            markets={"Z74.SI": "sg"},
        ))

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].document_type, "annual_report")
        self.assertEqual(result[1].document_type, "share_buyback")
        self.assertEqual(result[0].published_at.hour, 12)
        self.assertEqual(result[0].raw_metadata["source_tier"], 2)
        self.assertEqual(
            result[0].raw_metadata["discovery_source"],
            "audited_builtin_ir",
        )
        self.assertEqual(
            result[0].raw_metadata["attachment_urls"],
            [result[0].url],
        )
        self.assertEqual(connector.last_collection_status, "partial")

    def test_builtin_singtel_malformed_or_empty_datamodel_fails_closed(self):
        source_row = builtin_sg_ir_sources()
        for body in (
            '<div component="ReportThreeColumns" datamodel="{}"></div>',
            '<div component="ReportThreeColumns" datamodel="not-json"></div>',
            "<html>Loading</html>",
        ):
            connector = SgIrConnector(
                sources=source_row,
                fetcher=lambda _url, response=body: response,
                rate_limit_seconds=0,
            )
            self.assertEqual(connector.collect(CollectionRequest(
                tickers=("Z74",),
                start_date=date(2026, 8, 18),
                end_date=date(2026, 8, 19),
                markets={"Z74": "sg"},
            )), [])
            self.assertEqual(connector.last_collection_status, "unavailable")

    def test_builtin_ocbc_regulatory_archive_binds_dates_and_multiple_documents(self):
        body = (FIXTURES / "ocbc_regulatory.html").read_text()
        ocbc = tuple(
            item for item in builtin_sg_ir_sources() if item.ticker == "O39"
        )
        connector = SgIrConnector(
            sources=ocbc,
            fetcher=lambda _url: body,
            rate_limit_seconds=0,
        )
        result = connector.collect(CollectionRequest(
            tickers=("O39.SI",),
            start_date=date(2025, 7, 1),
            end_date=date(2026, 8, 20),
            markets={"O39.SI": "sg"},
        ))

        self.assertEqual(len(result), 6)
        self.assertEqual(result[0].document_type, "financing")
        self.assertEqual(result[1].document_type, "acquisition_disposal")
        self.assertEqual(result[2].published_at.date(), date(2025, 11, 26))
        self.assertEqual(result[3].published_at.date(), date(2025, 11, 26))
        self.assertEqual(result[4].published_at.date(), date(2025, 7, 18))
        self.assertEqual(result[5].published_at.date(), date(2025, 7, 16))
        self.assertTrue(all(item.url.startswith("https://www.ocbc.com/") for item in result))

    def test_sg_ir_has_audited_builtin_source_without_environment_config(self):
        self.assertIsNone(SgIrConnector.configuration_error())
        connector = SgIrConnector.from_environment()
        self.assertEqual(
            [item.source_id for item in connector._sources],
            [
                "singtel-stock-exchange-announcements",
                "ocbc-major-regulatory-announcements",
            ],
        )

    def test_shareinvestor_template_binds_its_own_date_and_nested_title(self):
        body = (FIXTURES / "shareinvestor.html").read_text()
        connector = SgIrConnector(
            sources=(source(fmt="html", adapter="shareinvestor"),),
            fetcher=lambda url: body,
            rate_limit_seconds=0,
        )
        result = connector.collect(request(end=date(2026, 8, 20)))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "Financial Results for H1 2026")
        self.assertEqual(result[0].published_at.date(), date(2026, 8, 20))

    def test_ir_sgx_permalink_pairs_real_connector_outputs(self):
        sgx_url = "https://links.sgx.com/1.0.0/corporate-announcements/Y93F0HCPJT1MS85Q/"
        ir_source = SgIrSource(
            source_id="singtel-ir", ticker="Z74", issuer="Singtel",
            exchange="SGX Mainboard",
            feed_url="https://investor.example.test/releases.json",
            format="json",
            url_rules=(
                SgIrUrlRule("investor.example.test", "/"),
                SgIrUrlRule("links.sgx.com", "/1.0.0/corporate-announcements"),
            ),
            filing_terms=("annual report",),
        )
        ir_body = json.dumps({"items": [{
            "id": "ir-1", "title": "Annual Report 2026",
            "published": "2026-06-23T18:39:50+08:00", "url": sgx_url,
        }]})
        ir_item = SgIrConnector(
            sources=(ir_source,), fetcher=lambda _url: ir_body,
            rate_limit_seconds=0,
        ).collect(CollectionRequest(
            tickers=("Z74",), start_date=date(2026, 6, 23),
            end_date=date(2026, 6, 23), markets={"Z74": "sg"},
        ))[0]
        sgx_fixture = Path(__file__).parent / "fixtures" / "sgx_announcements" / "detail_two_attachments.html"
        sgx_item = SgxAnnouncementConnector(
            discoveries=(SgxAnnouncementDiscovery(sgx_url, "issuer_ir", ticker="Z74"),),
            fetcher=lambda _url: sgx_fixture.read_text(),
            sleeper=lambda _seconds: None,
        ).collect(CollectionRequest(
            tickers=("Z74",), start_date=date(2026, 6, 23),
            end_date=date(2026, 6, 23), markets={"Z74": "sg"},
        ))[0]
        self.assertEqual(
            dedupe_key(asdict(ir_item)), dedupe_key(asdict(sgx_item))
        )

    def test_blocked_http_is_not_retried_and_is_unavailable(self):
        calls = []
        def blocked(url):
            calls.append(url)
            from investment_monitor.sources.sg_ir.connector import SgIrRequestError
            raise SgIrRequestError("HTTP 403")
        connector = SgIrConnector(sources=(source(),), fetcher=blocked, retry_attempts=4, rate_limit_seconds=0)
        self.assertEqual(connector.collect(request()), [])
        self.assertEqual(calls, [source().feed_url])
        self.assertEqual(connector.last_collection_status, "unavailable")

    def test_repeated_configured_page_fails_closed(self):
        body = (FIXTURES / "issuer_feed.xml").read_text()
        connector = SgIrConnector(sources=(source(pages=("https://investor.example.test/releases/page2",)),), fetcher=lambda url: body, rate_limit_seconds=0)
        self.assertEqual(connector.collect(request()), [])
        self.assertEqual(connector.last_source_statuses, {"dbs-ir": "unavailable"})

    def test_html_without_rows_is_not_empty_success(self):
        connector = SgIrConnector(sources=(source(fmt="html", adapter="shareinvestor"),), fetcher=lambda url: "<html>Loading</html>", rate_limit_seconds=0)
        self.assertEqual(connector.collect(request()), [])
        self.assertEqual(connector.last_collection_status, "unavailable")

    def test_load_strict_local_configuration(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            path.write_text(json.dumps({"schema": "sg_ir_sources/v1", "sources": [{
                "source_id": "d05", "ticker": "D05-SG", "issuer": "DBS", "exchange": "SGX Mainboard",
                "feed_url": "https://investor.example.test/feed", "format": "json", "url_rules": [{"host": "investor.example.test"}],
                "filing_terms": ["results"], "issuer_type": "ordinary_share"
            }]}))
            loaded = load_sources_from_path(path)
        self.assertEqual(loaded[0].ticker, "D05")
        self.assertEqual(loaded[0].format, "json")

    def test_outside_attachment_is_rejected(self):
        body = '{"items":[{"id":"1","title":"Financial Results","published":"2026-08-18T10:00:00+08:00","url":"https://investor.example.test/a","attachments":["https://evil.test/x.pdf"]}]}'
        connector = SgIrConnector(sources=(source(fmt="json"),), fetcher=lambda url: body, rate_limit_seconds=0)
        self.assertEqual(connector.collect(request()), [])
        self.assertEqual(connector.last_collection_status, "unavailable")


if __name__ == "__main__":
    unittest.main()
