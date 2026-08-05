from datetime import date, datetime, timezone
import unittest

from investment_monitor import (
    CollectionRequest,
    KindConnector,
    KindRequestError,
)


class FakeClient:
    def __init__(self, records=None, error=None) -> None:
        self.records = records or []
        self.error = error
        self.calls: list = []

    def search_disclosures(self, stock_code, start_date, end_date):
        self.calls.append((stock_code, start_date, end_date))
        if self.error is not None:
            raise self.error
        return self.records

    def viewer_url(self, acpt_no: str) -> str:
        return (
            "https://kind.krx.co.kr/common/disclsviewer.do"
            f"?method=searchInitInfo&acptNo={acpt_no}&docNo="
        )


def record(
    *,
    acpt_no: str = "20260805000501",
    title: str = "임원ㆍ주요주주특정증권등소유상황보고서",
    datetime_text: str = "2026-08-05 15:40",
    company_name: str = "삼성전자",
) -> dict:
    return {
        "acpt_no": acpt_no,
        "rcept_no": acpt_no,
        "title": title,
        "company_name": company_name,
        "datetime_text": datetime_text,
        "market": "유가증권",
        "submitter": "황상준",
    }


class KindConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            markets=markets,
        )

    def test_non_kr_markets_are_skipped_with_zero_http(self) -> None:
        client = FakeClient()
        connector = KindConnector(client=client)

        items = connector.collect(
            self.request(("AAPL", "0700"), {"AAPL": "us", "0700": "hk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(client.calls, [])

    def test_kr_maps_records_into_filings_items(self) -> None:
        client = FakeClient(
            records=[
                record(),
                record(
                    acpt_no="20260731000001",
                    datetime_text="2026-07-31 09:00",
                ),
            ]
        )
        connector = KindConnector(client=client)

        items = connector.collect(
            self.request(("005930",), {"005930": "kr"})
        )

        self.assertEqual(len(items), 1)
        first = items[0]
        self.assertEqual(first.source, "kind")
        self.assertEqual(first.source_type, "regulatory_filing")
        self.assertEqual(first.external_id, "20260805000501")
        self.assertEqual(first.tickers, ("005930",))
        self.assertEqual(first.issuer, "삼성전자")
        self.assertEqual(first.title, "임원ㆍ주요주주특정증권등소유상황보고서")
        self.assertEqual(first.document_type, "kind_disclosure")
        self.assertEqual(first.market, "kr")
        self.assertIn("acptNo=20260805000501", first.url)
        self.assertEqual(first.raw_metadata["rcept_no"], "20260805000501")
        self.assertEqual(first.raw_metadata["provider"], "kind")
        self.assertIsNone(first.summary)
        self.assertEqual(
            first.published_at,
            datetime(2026, 8, 5, 6, 40, tzinfo=timezone.utc),
        )
        self.assertEqual(client.calls[0][0], "005930")

    def test_kr_ticker_normalization_uses_six_digit_code(self) -> None:
        client = FakeClient(records=[record()])
        connector = KindConnector(client=client)

        items = connector.collect(
            self.request(("5930",), {"5930": "kr"})
        )

        self.assertEqual(client.calls[0][0], "005930")
        self.assertEqual(items[0].tickers, ("005930",))

    def test_failure_is_recorded_and_raised_for_single_ticker(self) -> None:
        client = FakeClient(error=KindRequestError("KIND request failed"))
        connector = KindConnector(client=client)

        with self.assertRaises(KindRequestError):
            connector.collect(
                self.request(("005930",), {"005930": "kr"})
            )

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "005930")
        self.assertIn("KIND request failed", connector.last_errors[0][1])

    def test_failed_kr_ticker_does_not_stop_other_kr_ticker(self) -> None:
        def failing_search(stock_code, start_date, end_date):
            if stock_code == "000270":
                raise KindRequestError("boom")
            return [record()]

        client = FakeClient()
        client.search_disclosures = failing_search  # type: ignore[method-assign]
        connector = KindConnector(client=client)

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
