from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    HkexDiConnector,
    HkexDiDataError,
    HkexDiRequestError,
)
from investment_monitor.registry import create_default_registry


def en_record(serial="20161003000123"):
    return {
        "serial": serial,
        "published_at": datetime(2016, 10, 3, tzinfo=timezone.utc),
        "person": "MA HUA TENG",
        "reason": "Acquisition of shares",
        "shares": "10,000,000",
        "pct": "0.52",
        "url": (
            "https://di.hkex.com.hk/filing/di/"
            f"NSSrchNotice.aspx?serial={serial}"
        ),
        "title": "Acquisition of shares",
        "stock_name": "TENCENT",
        "lang": "EN",
    }


def zh_record(serial="20161003000123"):
    return {
        "serial": serial,
        "published_at": datetime(2016, 10, 3, tzinfo=timezone.utc),
        "person": "馬化騰",
        "reason": "收購股份",
        "shares": "10,000,000",
        "pct": "0.52",
        "url": (
            "https://di.hkex.com.hk/filing/di/"
            f"NSSrchNotice.aspx?serial={serial}"
        ),
        "title": "收購股份",
        "stock_name": "騰訊控股",
        "lang": "ZH",
    }


class FakeClient:
    def __init__(self, en=None, zh=None, error=None) -> None:
        self.en = en or []
        self.zh = zh or []
        self.error = error
        self.calls: list = []

    def search_disclosures(self, stock_code, start_date, end_date, lang="EN"):
        self.calls.append((stock_code, lang))
        if self.error is not None:
            raise self.error
        return self.zh if lang == "ZH" else self.en


class HkexDiConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2016, 10, 3),
            end_date=date(2016, 10, 4),
            markets=markets,
        )

    def test_non_hk_markets_are_skipped_with_zero_http(self) -> None:
        class ExplodingClient:
            def search_disclosures(self, *args, **kwargs):
                raise AssertionError("HKEX DI must not be called for non-HK")

        connector = HkexDiConnector(client=ExplodingClient())

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_hk_maps_notices_into_filings_items(self) -> None:
        connector = HkexDiConnector(client=FakeClient(en=[en_record()]))

        items = connector.collect(
            self.request(("00700",), {"00700": "hk"})
        )

        self.assertEqual(len(items), 1)
        first = items[0]
        self.assertEqual(first.source, "hkex_di")
        self.assertEqual(first.source_type, "regulatory_filing")
        self.assertEqual(first.document_type, "di_notice")
        self.assertEqual(first.external_id, "20161003000123")
        self.assertEqual(first.tickers, ("00700",))
        self.assertEqual(first.market, "hk")
        self.assertEqual(first.title, "Acquisition of shares")
        self.assertEqual(
            first.url,
            "https://di.hkex.com.hk/filing/di/"
            "NSSrchNotice.aspx?serial=20161003000123",
        )
        self.assertEqual(first.raw_metadata["person"], "MA HUA TENG")
        self.assertEqual(first.raw_metadata["reason"], "Acquisition of shares")
        self.assertEqual(first.raw_metadata["shares"], "10,000,000")
        self.assertEqual(first.raw_metadata["pct"], "0.52")

    def test_bilingual_notices_merge_by_serial(self) -> None:
        connector = HkexDiConnector(
            client=FakeClient(
                en=[en_record("20161003000123")],
                zh=[zh_record("20161003000123")],
            )
        )

        items = connector.collect(
            self.request(("00700",), {"00700": "hk"})
        )

        self.assertEqual(len(items), 1)
        first = items[0]
        self.assertEqual(first.title, "Acquisition of shares")
        self.assertEqual(first.raw_metadata["title_zh"], "收購股份")
        self.assertEqual(first.raw_metadata["langs"], "en+zh")
        self.assertEqual(connector._client.calls[0], ("00700", "EN"))
        self.assertEqual(connector._client.calls[1], ("00700", "ZH"))

    def test_single_ticker_data_error_raises_and_records(self) -> None:
        connector = HkexDiConnector(
            client=FakeClient(
                error=HkexDiDataError(
                    "HKEX DI public search covers 2003-04-01 to 2017-10-02"
                )
            )
        )

        with self.assertRaises(HkexDiRequestError):
            connector.collect(self.request(("00700",), {"00700": "hk"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "00700")

    def test_registry_registers_hkex_di_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("hkex_di"))
        self.assertEqual(registry.secret_fields_for("hkex_di"), ())

    def test_settings_loads_hkex_di_enabled(self) -> None:
        from investment_monitor.config import load_settings

        settings = load_settings(Path("config/settings.yaml"))

        self.assertIn("hkex_di", settings.enabled_sources)


if __name__ == "__main__":
    unittest.main()
