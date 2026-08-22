from datetime import date, datetime, timezone
import unittest

from investment_monitor import (
    CollectionRequest,
    HkexNewsConnector,
    HkexNewsRequestError,
)
from investment_monitor.registry import create_default_registry


def en_record(news_id="20260303001234", title="Board Meeting Date"):
    return {
        "news_id": news_id,
        "title": title,
        "published_at": datetime(2026, 3, 3, 8, 40, tzinfo=timezone.utc),
        "url": "https://www1.hkexnews.hk/listedco/20260303001234.htm",
        "stock_code": "00700",
        "stock_name": "TENCENT",
        "file_type": "Announcements and Notices",
        "file_link": "/listedco/20260303001234.htm",
    }


def zh_record(news_id="20260303001234", title="董事會會議日期"):
    return {
        "news_id": news_id,
        "title": title,
        "published_at": datetime(2026, 3, 3, 8, 40, tzinfo=timezone.utc),
        "url": "https://www1.hkexnews.hk/listedco/20260303001234.htm",
        "stock_code": "00700",
        "stock_name": "騰訊控股",
        "file_type": "公告及通告",
        "file_link": "/listedco/20260303001234.htm",
    }


class FakeClient:
    def __init__(self, stock_id="15157", en=None, zh=None, error=None) -> None:
        self.stock_id = stock_id
        self.en = en or []
        self.zh = zh or []
        self.error = error
        self.calls: list = []

    def stock_id_for(self, ticker):
        self.calls.append(("stock_id_for", ticker))
        return self.stock_id

    def search_disclosures(self, stock_id, start_date, end_date, lang="E"):
        self.calls.append(("search", stock_id, lang))
        if self.error is not None:
            raise self.error
        return self.zh if lang == "zh" else self.en


class HkexNewsConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
            markets=markets,
        )

    def test_non_hk_markets_are_skipped_with_zero_http(self) -> None:
        class ExplodingClient:
            def stock_id_for(self, ticker):
                raise AssertionError("HKEXnews must not be called for non-HK")

            def search_disclosures(self, *args, **kwargs):
                raise AssertionError("HKEXnews must not be called for non-HK")

        connector = HkexNewsConnector(client=ExplodingClient())

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_hk_maps_records_into_filings_items(self) -> None:
        client = FakeClient(en=[en_record()])
        connector = HkexNewsConnector(client=client)

        items = connector.collect(
            self.request(("00700",), {"00700": "hk"})
        )

        self.assertEqual(len(items), 1)
        first = items[0]
        self.assertEqual(first.source, "hkexnews")
        self.assertEqual(first.source_type, "regulatory_filing")
        self.assertEqual(first.external_id, "20260303001234")
        self.assertEqual(first.tickers, ("00700",))
        self.assertEqual(first.market, "hk")
        self.assertEqual(first.document_type, "hkex_announcement")
        self.assertEqual(first.title, "Board Meeting Date")
        self.assertEqual(
            first.url,
            "https://www1.hkexnews.hk/listedco/20260303001234.htm",
        )
        self.assertEqual(
            first.raw_metadata["official_document_url"],
            first.url,
        )
        self.assertEqual(
            first.raw_metadata["raw_announcement_en"]["news_id"],
            "20260303001234",
        )
        self.assertEqual(client.calls.count(("search", "15157", "E")), 1)
        self.assertEqual(client.calls.count(("search", "15157", "zh")), 1)
        self.assertEqual(connector.last_collection_status, "success")

    def test_bilingual_records_merge_by_news_id(self) -> None:
        client = FakeClient(
            en=[
                en_record("20260303001234", "Board Meeting Date"),
                en_record("20260303001235", "Monthly Return"),
            ],
            zh=[
                zh_record("20260303001234", "董事會會議日期"),
                zh_record("20260303001236", "翌日披露報表"),
            ],
        )
        connector = HkexNewsConnector(client=client)

        items = connector.collect(
            self.request(("00700",), {"00700": "hk"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertEqual(set(by_id), {"20260303001234", "20260303001235", "20260303001236"})
        merged = by_id["20260303001234"]
        self.assertEqual(merged.title, "Board Meeting Date")
        self.assertEqual(merged.raw_metadata["title_zh"], "董事會會議日期")
        self.assertEqual(merged.raw_metadata["title_en"], "Board Meeting Date")
        zh_only = by_id["20260303001236"]
        self.assertEqual(zh_only.title, "翌日披露報表")
        self.assertEqual(zh_only.raw_metadata["title_zh"], "翌日披露報表")
        en_only = by_id["20260303001235"]
        self.assertEqual(en_only.title, "Monthly Return")

    def test_missing_stock_id_fails_closed_without_search(self) -> None:
        client = FakeClient(stock_id=None)
        connector = HkexNewsConnector(client=client)

        with self.assertRaises(HkexNewsRequestError):
            connector.collect(self.request(("00700",), {"00700": "hk"}))

        self.assertEqual(connector.last_errors[0][0], "00700")
        self.assertEqual(client.calls, [("stock_id_for", "00700")])
        self.assertEqual(connector.last_collection_status, "failure")

    def test_hk_empty_search_packet_is_a_failure(self) -> None:
        client = FakeClient(en=[], zh=[])
        connector = HkexNewsConnector(client=client)

        with self.assertRaises(HkexNewsRequestError):
            connector.collect(self.request(("00700",), {"00700": "hk"}))

        self.assertEqual(connector.last_errors, (("00700", "empty_packet"),))

    def test_hk_empty_packet_is_recorded_for_multi_ticker_requests(self) -> None:
        client = FakeClient(en=[], zh=[])
        connector = HkexNewsConnector(client=client)

        items = connector.collect(
            self.request(("00700", "09988"), {"00700": "hk", "09988": "hk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(
            connector.last_errors,
            (("00700", "empty_packet"), ("09988", "empty_packet")),
        )

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        client = FakeClient(
            error=HkexNewsRequestError("HKEXnews request failed: test")
        )
        connector = HkexNewsConnector(client=client)

        with self.assertRaises(HkexNewsRequestError):
            connector.collect(self.request(("00700",), {"00700": "hk"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "00700")
        self.assertEqual(connector.last_collection_status, "failure")

    def test_mismatched_stock_code_fails_closed(self) -> None:
        record = en_record()
        record["stock_code"] = "00001"
        connector = HkexNewsConnector(client=FakeClient(en=[record]))

        with self.assertRaises(HkexNewsRequestError):
            connector.collect(self.request(("00700",), {"00700": "hk"}))

        self.assertEqual(connector.last_errors[0][0], "00700")

    def test_registry_registers_hkexnews_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("hkexnews"))
        self.assertEqual(registry.secret_fields_for("hkexnews"), ())


if __name__ == "__main__":
    unittest.main()
