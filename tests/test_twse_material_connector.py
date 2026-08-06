import json
from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    TwseMaterialConnector,
    TwseMaterialRequestError,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.twse_material.client import _parse_records


FIXTURES = Path(__file__).parent / "fixtures" / "twse_material"


def fixture_records() -> list:
    payload = json.loads(
        (FIXTURES / "t187ap04_L.json").read_text(encoding="utf-8")
    )
    return _parse_records(payload, api_url="https://example.test/t187ap04_L")


class FakeClient:
    def __init__(self, records=None, error=None) -> None:
        self.records = records if records is not None else fixture_records()
        self.error = error
        self.calls: list = []

    def fetch_material(self):
        self.calls.append("fetch_material")
        if self.error is not None:
            raise self.error
        return self.records


class TwseMaterialConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            markets=markets,
        )

    def test_non_tw_markets_are_skipped_with_zero_http(self) -> None:
        class ExplodingClient:
            def fetch_material(self):
                raise AssertionError("TWSE must not be called for non-TW")

        connector = TwseMaterialConnector(client=ExplodingClient())

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_tw_collects_only_requested_tickers_in_window(self) -> None:
        connector = TwseMaterialConnector(client=FakeClient())

        items = connector.collect(
            self.request(("2330", "1721"), {"2330": "tw", "1721": "tw"})
        )

        by_ticker = {item.tickers[0]: item for item in items}
        self.assertEqual(set(by_ticker), {"2330", "1721"})
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source, "twse_material")
        self.assertEqual(items[0].source_type, "regulatory_filing")
        self.assertEqual(items[0].document_type, "tw_material")
        self.assertEqual(items[0].market, "tw")
        self.assertEqual(
            items[0].url,
            "https://mops.twse.com.tw/mops/web/t05st09_ifrs",
        )
        self.assertIn("calendar_date", items[0].raw_metadata)
        self.assertIn("api_url", items[0].raw_metadata)

    def test_out_of_window_records_are_excluded(self) -> None:
        connector = TwseMaterialConnector(client=FakeClient())

        items = connector.collect(
            self.request(("2330",), {"2330": "tw"})
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].tickers, ("2330",))
        self.assertEqual(items[0].title, "公告本公司一一五年七月份營收報告")

    def test_single_ticker_failure_raises(self) -> None:
        connector = TwseMaterialConnector(
            client=FakeClient(
                error=TwseMaterialRequestError("twse blocked")
            )
        )

        with self.assertRaises(TwseMaterialRequestError):
            connector.collect(self.request(("2330",), {"2330": "tw"}))

        self.assertEqual(len(connector.last_errors), 1)

    def test_registry_registers_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("twse_material"))
        self.assertEqual(registry.secret_fields_for("twse_material"), ())

    def test_settings_loads_twse_material_enabled(self) -> None:
        from investment_monitor.config import load_settings

        settings = load_settings(Path("config/settings.yaml"))

        self.assertIn("twse_material", settings.enabled_sources)


if __name__ == "__main__":
    unittest.main()
