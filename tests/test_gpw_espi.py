"""Tests for the GPW ESPI/EBI disclosure connector (market=pl, PL-4 D1).

PL-4 re-spike (2026-08-10) found the official GPW reports page
``www.gpw.pl/komunikaty``: a server-rendered, key-free ESPI/EBI list that
supports ISIN filtering and pagination. This replaced the PL-1 A3
"not wired" boundary for the official page (``espi.gpw.pl`` itself remains
unreachable and EQS stays empty for Polish ISINs).
"""

from datetime import date, datetime, timezone
from pathlib import Path
import unittest
from urllib.parse import urlsplit

from investment_monitor import (
    CollectionRequest,
    GpwEspiConnector,
    GpwEspiDataError,
    GpwEspiRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "gpw_espi"


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    def __init__(self, fixtures: dict) -> None:
        self.fixtures = fixtures
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        path = urlsplit(url).path
        if path in self.fixtures:
            return FakeResponse(self.fixtures[path])
        raise AssertionError(f"unexpected url: {url}")


def client_opener(**kwargs):
    return FakeOpener(
        {
            "/komunikaty": (
                FIXTURES / "komunikaty_pko.html"
            ).read_bytes(),
        },
        **kwargs,
    )


def empty_opener(**kwargs):
    return FakeOpener(
        {
            "/komunikaty": (
                FIXTURES / "komunikaty_empty.html"
            ).read_bytes(),
        },
        **kwargs,
    )


class GpwEspiClientTests(unittest.TestCase):
    def test_parses_reports_and_filters_warsaw_window(self) -> None:
        from investment_monitor.sources.gpw_espi.client import (
            GpwEspiClient,
            _parse_page,
        )

        body = (FIXTURES / "komunikaty_pko.html").read_bytes()
        records = _parse_page(body, "https://www.gpw.pl/")
        self.assertEqual(len(records), 4)

        opener = client_opener()
        client = GpwEspiClient(opener=opener, requests_per_second=1000)
        fetched = client.fetch_reports(
            "PLPKO0000016",
            date(2026, 8, 1),
            date(2026, 8, 10),
        )

        self.assertEqual(len(fetched), 3)
        first = fetched[0]
        self.assertEqual(first["external_id"], "495125")
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 10, 12, 58, 19, tzinfo=timezone.utc),
        )
        self.assertEqual(first["title"], "Rejestracja zmiany Statutu Emitenta")
        self.assertEqual(first["report_type"], "ESPI")
        self.assertEqual(first["report_number"], "25/2026")
        self.assertEqual(first["isin"], "PLPKO0000016")
        self.assertEqual(
            first["company_name"],
            "POWSZECHNA KASA OSZCZEDNOSCI BANK POLSKI",
        )
        self.assertIn("geru_id=495125", first["url"])
        # 10-08 01:30 Warsaw is 09-08 23:30 UTC but still the Warsaw day
        # 2026-08-10, so it is kept by the Warsaw-day window.
        warsaw_boundary = next(
            record
            for record in fetched
            if record["external_id"] == "495124"
        )
        self.assertEqual(
            warsaw_boundary["published"],
            datetime(2026, 8, 9, 23, 30, tzinfo=timezone.utc),
        )
        self.assertIn("searchText=PLPKO0000016", opener.requested[0])
        self.assertIn("limit=100", opener.requested[0])
        self.assertIn("offset=0", opener.requested[0])

    def test_empty_result_page_returns_empty_list(self) -> None:
        from investment_monitor.sources.gpw_espi.client import (
            GpwEspiClient,
        )

        client = GpwEspiClient(opener=empty_opener(), requests_per_second=1000)

        fetched = client.fetch_reports(
            "PLXXXX0000000",
            date(2026, 8, 1),
            date(2026, 8, 10),
        )

        self.assertEqual(fetched, [])

    def test_broken_page_raises_data_error(self) -> None:
        from investment_monitor.sources.gpw_espi.client import _parse_page

        with self.assertRaises(GpwEspiDataError):
            _parse_page(
                b"<html><body>Request Rejected</body></html>",
                "https://www.gpw.pl/",
            )


class GpwEspiConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 10),
            markets=markets,
        )

    def make_connector(self, opener=None, universe=None):
        from investment_monitor.sources.gpw_espi.client import (
            GpwEspiClient,
        )

        connector = GpwEspiConnector(
            client=GpwEspiClient(
                opener=opener or client_opener(),
                requests_per_second=1000,
            ),
            universe=(
                universe
                if universe is not None
                else {
                    "PKO": {
                        "name": "POWSZECHNA KASA OSZCZEDNOSCI BANK POLSKI",
                        "exchange": "GPW Main Market",
                        "board": "GPW Main Market",
                        "isin": "PLPKO0000016",
                    }
                }
            ),
        )
        return connector

    def test_non_pl_markets_are_skipped_with_zero_http(self) -> None:
        opener = client_opener()
        connector = self.make_connector(opener=opener)

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_pl_maps_filings_with_canonical_ticker(self) -> None:
        opener = client_opener()
        connector = self.make_connector(opener=opener)

        items = connector.collect(
            self.request(("PKO.WA",), {"PKO.WA": "pl"})
        )

        self.assertEqual(len(items), 3)
        by_id = {item.external_id: item for item in items}
        first = by_id["495125"]
        self.assertEqual(first.source, "gpw_espi")
        self.assertEqual(first.source_type, "regulatory_filing")
        self.assertEqual(first.tickers, ("PKO",))
        self.assertEqual(first.market, "pl")
        self.assertEqual(
            first.title,
            "Rejestracja zmiany Statutu Emitenta",
        )
        self.assertEqual(first.document_type, "espi_25/2026")
        self.assertEqual(first.issuer, "POWSZECHNA KASA OSZCZEDNOSCI BANK POLSKI")
        self.assertIn("geru_id=495125", first.url)
        self.assertEqual(first.raw_metadata["isin"], "PLPKO0000016")
        self.assertIn("searchText=PLPKO0000016", opener.requested[0])

    def test_missing_universe_identity_is_skipped_honestly(self) -> None:
        opener = client_opener()
        connector = self.make_connector(opener=opener, universe={})

        with self.assertRaises(GpwEspiRequestError):
            connector.collect(self.request(("PKO",), {"PKO": "pl"}))

        self.assertEqual(connector.last_errors, (("PKO", "no_universe_identity"),))
        self.assertEqual(opener.requested, [])

    def test_registry_registers_gpw_espi_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("gpw_espi"))
        self.assertEqual(registry.secret_fields_for("gpw_espi"), ())


if __name__ == "__main__":
    unittest.main()
