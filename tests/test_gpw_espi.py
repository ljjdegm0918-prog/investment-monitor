"""Tests for the GPW ESPI/EBI disclosure connector (market=pl, PL-4 D1).

PL-4 re-spike (2026-08-10) found the official GPW reports page
``www.gpw.pl/komunikaty``: a server-rendered, key-free ESPI/EBI list that
supports ISIN filtering and pagination. This replaced the PL-1 A3
"not wired" boundary for the official page (``espi.gpw.pl`` itself remains
unreachable and EQS stays empty for Polish ISINs).
"""

from datetime import date, datetime, timezone
from http.client import IncompleteRead
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock
from urllib.parse import urlsplit

from investment_monitor import (
    CollectionRequest,
    GpwEspiConnector,
    GpwEspiDataError,
    GpwEspiRequestError,
)
from investment_monitor.registry import create_default_registry
from provenance_assertions import assert_official_provenance


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


class TruncatingResponse:
    def __init__(self, partial: bytes, expected: int = 999) -> None:
        self._partial = partial
        self._expected = expected

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        raise IncompleteRead(self._partial, self._expected)


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


class ScriptedOpener:
    def __init__(self, bodies) -> None:
        self.bodies = list(bodies)
        self.requested: list = []

    def __call__(self, request, timeout=None):
        self.requested.append(request.full_url)
        if not self.bodies:
            raise AssertionError(f"unexpected extra request: {request.full_url}")
        return FakeResponse(self.bodies.pop(0))


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
    def test_full_limit_page_with_confirmed_next_page_raises_truncation(self) -> None:
        from investment_monitor.sources.gpw_espi.client import GpwEspiClient

        full_page = (FIXTURES / "komunikaty_pko.html").read_bytes()
        opener = ScriptedOpener((full_page, full_page))
        client = GpwEspiClient(opener=opener, requests_per_second=1000)

        with self.assertRaises(GpwEspiDataError):
            client.fetch_reports(
                "PLPKO0000016",
                date(2026, 7, 1),
                date(2026, 8, 10),
                page_size=4,
                max_pages=1,
            )

        self.assertEqual(len(opener.requested), 2)
        self.assertIn("offset=4", opener.requested[1])

    def test_full_final_page_with_empty_probe_is_not_truncation(self) -> None:
        from investment_monitor.sources.gpw_espi.client import GpwEspiClient

        full_page = (FIXTURES / "komunikaty_pko.html").read_bytes()
        empty_page = (FIXTURES / "komunikaty_empty.html").read_bytes()
        opener = ScriptedOpener((full_page, empty_page))
        client = GpwEspiClient(opener=opener, requests_per_second=1000)

        records = client.fetch_reports(
            "PLPKO0000016",
            date(2026, 7, 1),
            date(2026, 8, 10),
            page_size=4,
            max_pages=1,
        )

        self.assertEqual(len(records), 4)
        self.assertEqual(len(opener.requested), 2)

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

    def test_incomplete_read_with_partial_html_is_usable(self) -> None:
        from investment_monitor.sources.gpw_espi.client import GpwEspiClient

        body = (FIXTURES / "komunikaty_pko.html").read_bytes()

        def opener(request, timeout=None):
            opener.requested.append(request.full_url)
            return TruncatingResponse(body)

        opener.requested = []
        client = GpwEspiClient(
            opener=opener,
            requests_per_second=1000,
            sleeper=lambda _delay: None,
        )

        fetched = client.fetch_reports(
            "PLPKO0000016",
            date(2026, 7, 1),
            date(2026, 8, 10),
        )

        self.assertGreaterEqual(len(fetched), 1)
        self.assertEqual(len(opener.requested), 1)

    def test_empty_incomplete_read_retries_then_succeeds(self) -> None:
        from investment_monitor.sources.gpw_espi.client import GpwEspiClient

        body = (FIXTURES / "komunikaty_pko.html").read_bytes()
        bodies = [TruncatingResponse(b""), FakeResponse(body)]

        def opener(request, timeout=None):
            opener.requested.append(request.full_url)
            return bodies.pop(0)

        opener.requested = []
        client = GpwEspiClient(
            opener=opener,
            requests_per_second=1000,
            sleeper=lambda _delay: None,
        )

        fetched = client.fetch_reports(
            "PLPKO0000016",
            date(2026, 7, 1),
            date(2026, 8, 10),
        )

        self.assertGreaterEqual(len(fetched), 1)
        self.assertEqual(len(opener.requested), 2)

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
        from investment_monitor.sources.gpw_espi.client import _parse_page
        payload = next(
            record["raw_payload"]
            for record in _parse_page(
                (FIXTURES / "komunikaty_pko.html").read_bytes(),
                "https://www.gpw.pl/",
            )
            if record["external_id"] == first.external_id
        )
        assert_official_provenance(
            self,
            first,
            expected_payload=payload,
            official_source_id=first.external_id,
            official_source_url=first.url,
            retrieval_url=opener.requested[0],
            raw_payload_format="html_list_item",
            classification_code=None,
            classification_label="espi",
            published_at_raw=payload["date"],
            published_timezone="Europe/Warsaw",
        )

    def test_missing_universe_identity_is_skipped_honestly(self) -> None:
        opener = client_opener()
        connector = self.make_connector(opener=opener, universe={})

        with self.assertRaises(GpwEspiRequestError):
            connector.collect(self.request(("PKO",), {"PKO": "pl"}))

        self.assertEqual(connector.last_errors, (("PKO", "no_universe_identity"),))
        self.assertEqual(opener.requested, [])

    def test_default_universe_cache_is_loaded_without_injection(self) -> None:
        """Production default: no universe argument means the PL cache."""
        from investment_monitor import (
            pl_universe_name_map,
            refresh_pl_universe,
        )
        from investment_monitor.sources.gpw_espi.client import (
            GpwEspiClient,
        )

        with TemporaryDirectory() as temporary_directory:
            universe_path = Path(temporary_directory) / "pl_universe.json"
            refresh_pl_universe(
                path=universe_path,
                opener=FakeOpener(
                    {
                        "/spolki": (
                            Path(__file__).parent
                            / "fixtures"
                            / "pl_universe"
                            / "gpw_main.html"
                        ).read_bytes(),
                    }
                ),
            )
            self.assertIn("PKO", pl_universe_name_map(universe_path))

            opener = client_opener()
            with mock.patch.dict(
                os.environ,
                {"PL_UNIVERSE_CACHE_PATH": str(universe_path)},
            ):
                connector = GpwEspiConnector(
                    client=GpwEspiClient(
                        opener=opener,
                        requests_per_second=1000,
                    )
                )
                items = connector.collect(
                    self.request(("PKO.WA",), {"PKO.WA": "pl"})
                )

            self.assertEqual(len(items), 3)
            self.assertEqual(items[0].tickers, ("PKO",))
            self.assertIn("searchText=PLPKO0000016", opener.requested[0])
            self.assertEqual(connector.last_errors, ())

    def test_typed_polish_isin_is_used_as_identity(self) -> None:
        opener = client_opener()
        connector = self.make_connector(opener=opener, universe={})

        items = connector.collect(
            self.request(("PLPKO0000016",), {"PLPKO0000016": "pl"})
        )

        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].tickers, ("PLPKO0000016",))
        self.assertEqual(connector.last_errors, ())
        self.assertIn("searchText=PLPKO0000016", opener.requested[0])

    def test_registry_registers_gpw_espi_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("gpw_espi"))
        self.assertEqual(registry.secret_fields_for("gpw_espi"), ())


if __name__ == "__main__":
    unittest.main()
