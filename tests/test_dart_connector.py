from datetime import date, datetime, timezone
import unittest

from investment_monitor import (
    CollectionRequest,
    DARTConnector,
    DartRequestError,
)


class FakeClient:
    def __init__(self, records=None, error=None) -> None:
        self.records = records or []
        self.error = error
        self.calls: list = []

    def get_list(self, *, corp_code: str, bgn_de: str, end_de: str):
        self.calls.append((corp_code, bgn_de, end_de))
        if self.error is not None:
            raise self.error
        return self.records


class FakeCache:
    def __init__(self, mapping=None) -> None:
        self.mapping = mapping or {}
        self.requests: list = []

    def resolve(self, ticker: str):
        self.requests.append(ticker)
        raw = ticker.strip()
        key = raw.zfill(6) if raw.isdigit() else raw.upper()
        return self.mapping.get(key)


def make_record(
    *,
    rcept_no: str = "20260801000001",
    report_nm: str = "사업보고서",
    rcept_dt: str = "20260801",
    en_title: str = None,
    pblntf_ty: str = "B001",
) -> dict:
    record = {
        "rcept_no": rcept_no,
        "report_nm": report_nm,
        "rcept_dt": rcept_dt,
        "corp_name": "삼성전자",
        "corp_code": "00593000",
        "flr_nm": "유가증권",
        "rm": "",
        "pblntf_ty": pblntf_ty,
    }
    if en_title is not None:
        record["en_title"] = en_title
    return record


class DARTConnectorTests(unittest.TestCase):
    def make_connector(self, client, cache) -> DARTConnector:
        return DARTConnector(client=client, cache=cache)

    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets=markets,
        )

    def test_non_kr_markets_are_skipped_with_zero_http(self) -> None:
        client = FakeClient()
        cache = FakeCache()
        connector = self.make_connector(client, cache)

        items = connector.collect(
            self.request(("AAPL", "0700"), {"AAPL": "us", "0700": "hk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(cache.requests, [])
        self.assertEqual(client.calls, [])

    def test_kr_without_corp_code_is_skipped_silently(self) -> None:
        client = FakeClient()
        cache = FakeCache()
        connector = self.make_connector(client, cache)

        items = connector.collect(
            self.request(("005930",), {"005930": "kr"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(cache.requests, ["005930"])
        self.assertEqual(client.calls, [])

    def test_kr_maps_disclosure_records_into_filings_items(self) -> None:
        client = FakeClient(
            records=[
                make_record(),
                make_record(
                    rcept_no="20260731000001",
                    report_nm="구공시",
                    rcept_dt="20260731",
                ),
                make_record(
                    rcept_no="20260801000002",
                    report_nm="분기보고서",
                    pblntf_ty="C001",
                    en_title="Quarterly report",
                ),
            ]
        )
        cache = FakeCache(
            {"005930": ("00593000", "삼성전자", "005930")}
        )
        connector = self.make_connector(client, cache)

        items = connector.collect(
            self.request(("005930",), {"005930": "kr"})
        )

        self.assertEqual(len(items), 2)
        annual = items[0]
        self.assertEqual(annual.source, "dart")
        self.assertEqual(annual.source_type, "regulatory_filing")
        self.assertEqual(annual.external_id, "20260801000001")
        self.assertEqual(annual.tickers, ("005930",))
        self.assertEqual(annual.issuer, "삼성전자")
        self.assertEqual(annual.title, "사업보고서")
        self.assertEqual(annual.document_type, "annual_report")
        self.assertEqual(annual.market, "kr")
        self.assertIsNone(annual.summary)
        self.assertIn("rcpNo=20260801000001", annual.url)
        self.assertEqual(annual.raw_metadata["corp_code"], "00593000")
        self.assertEqual(annual.published_at.date(), date(2026, 8, 1))

        quarterly = items[1]
        self.assertEqual(quarterly.document_type, "quarterly_report")
        self.assertEqual(quarterly.summary, "Quarterly report")
        self.assertEqual(quarterly.raw_metadata["en_title"], "Quarterly report")
        self.assertEqual(client.calls, [("00593000", "20260801", "20260802")])

    def test_kr_ticker_normalization_uses_six_digit_code(self) -> None:
        client = FakeClient(records=[make_record()])
        cache = FakeCache(
            {"005930": ("00593000", "삼성전자", "005930")}
        )
        connector = self.make_connector(client, cache)

        items = connector.collect(
            self.request(("5930",), {"5930": "kr"})
        )

        self.assertEqual(items[0].tickers, ("005930",))
        self.assertEqual(cache.requests, ["5930"])

    def test_error_status_becomes_ticker_failure(self) -> None:
        client = FakeClient(
            error=DartRequestError(
                "OpenDART list status 013: 사용할 수 없는 키",
                status_code="013",
            )
        )
        cache = FakeCache(
            {"005930": ("00593000", "삼성전자", "005930")}
        )
        connector = self.make_connector(client, cache)

        with self.assertRaises(DartRequestError):
            connector.collect(
                self.request(("005930",), {"005930": "kr"})
            )

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "005930")
        self.assertIn("013", connector.last_errors[0][1])

    def test_failed_kr_ticker_does_not_stop_other_kr_ticker(self) -> None:
        def failing_get_list(*, corp_code, bgn_de, end_de):
            if corp_code == "00027000":
                raise DartRequestError("boom")
            return [make_record()]

        client = FakeClient()
        client.get_list = failing_get_list  # type: ignore[method-assign]
        cache = FakeCache(
            {
                "005930": ("00593000", "삼성전자", "005930"),
                "000270": ("00027000", "기아", "000270"),
            }
        )
        connector = self.make_connector(client, cache)

        items = connector.collect(
            self.request(
                ("005930", "000270"),
                {"005930": "kr", "000270": "kr"},
            )
        )

        self.assertEqual({item.tickers for item in items}, {("005930",)})
        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "000270")


if __name__ == "__main__":
    unittest.main()
