from datetime import date, datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from investment_monitor import (
    CollectionRequest,
    ConnectorUnavailableError,
    TDnetCollectionError,
    TDnetCompleteness,
    TDnetConnector,
    TDnetDataError,
    TDnetHTTPClient,
    SQLiteInformationRepository,
)


DAY = date(2026, 8, 7)
OFFICIAL_ROOT = "https://official.example.test/inbs/"
YANOSHIN_ROOT = "https://crosscheck.example.test/list/"
DEFAULT_LIMIT = 2000


def yanoshin_url(day_text="20260807", limit=DEFAULT_LIMIT):
    return YANOSHIN_ROOT + f"{day_text}.json?limit={limit}"


def row(code="1111", name="匿名株式会社", title="決算短信", at="09:00", suffix="a"):
    return (
        f"<tr><td>{at}</td><td>{code}</td><td>{name}</td>"
        f'<td><a href="docs/{suffix}.pdf">{title}</a></td></tr>'
    )


def page(declared, *rows, page_link=None):
    link = f'<a href="{page_link}">次頁</a>' if page_link else ""
    return f"<html><body><p>全 {declared} 件</p>{link}<table>{''.join(rows)}</table></body></html>".encode()


def crosscheck(*records):
    return json.dumps(list(records), ensure_ascii=False).encode()


def crosscheck_record(code="1111", title="決算短信", at="2026-08-07 09:00:00"):
    return {
        "company_code": code,
        "company_name": "匿名株式会社",
        "title": title,
        "pubdate": at,
        "document_url": "https://crosscheck.example.test/document.pdf",
    }


class FakeClient:
    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls = []

    def get_bytes(self, url, accept):
        self.calls.append((url, accept))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def request(*tickers, markets=None):
    return CollectionRequest(
        tickers=tickers or ("1111",),
        start_date=DAY,
        end_date=DAY,
        markets=markets or {ticker: "jp" for ticker in (tickers or ("1111",))},
    )


def connector_for(official, yanoshin, **kwargs):
    limit = kwargs.get("yanoshin_limit", DEFAULT_LIMIT)
    responses = {
        OFFICIAL_ROOT + "I_list_001_20260807.html": official,
        yanoshin_url(limit=limit): yanoshin,
    }
    responses.update(kwargs.pop("responses", {}))
    client = FakeClient(responses)
    now = kwargs.pop(
        "now",
        lambda: datetime(2026, 8, 7, 12, tzinfo=timezone.utc),
    )
    connector = TDnetConnector(
        client,
        official_base_url=OFFICIAL_ROOT,
        yanoshin_base_url=YANOSHIN_ROOT,
        now=now,
        **kwargs,
    )
    return connector, client


class TDnetConnectorTests(unittest.TestCase):
    def test_normal_single_page_converts_jst_to_utc_and_keeps_provenance(self):
        connector, _ = connector_for(
            page(1, row()),
            crosscheck(crosscheck_record()),
        )

        items = connector.collect(request("1111"))

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.published_at, datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(item.market, "jp")
        self.assertEqual(item.tickers, ("1111",))
        self.assertEqual(item.raw_metadata["published_timezone"], "Asia/Tokyo")
        self.assertEqual(item.raw_metadata["official_source_url"], OFFICIAL_ROOT + "I_list_001_20260807.html")
        self.assertFalse(item.raw_metadata["official_id_available"])
        self.assertEqual(
            connector.last_reports[0].status,
            TDnetCompleteness.PROVISIONAL,
        )

    def test_empty_response_is_complete_when_both_sources_are_empty(self):
        connector, _ = connector_for(page(0), crosscheck())
        self.assertEqual(connector.collect(request("1111")), [])
        self.assertEqual(connector.last_reports[0].official_count, 0)

    def test_multi_page_discovers_every_page_and_sorts_output(self):
        page_two_url = OFFICIAL_ROOT + "I_list_002_20260807.html"
        connector, client = connector_for(
            page(2, row("2222", title="後の公告", at="10:00", suffix="b"), page_link="I_list_002_20260807.html"),
            crosscheck(
                crosscheck_record("2222", "後の公告", "2026-08-07 10:00:00"),
                crosscheck_record("1111", "先の公告", "2026-08-07 09:00:00"),
            ),
            responses={page_two_url: b"<html><body><table>" + row("1111", title="先の公告", at="09:00").encode() + b"</table></body></html>"},
        )

        items = connector.collect(request("2222", "1111"))

        self.assertEqual([item.tickers[0] for item in items], ["1111", "2222"])
        self.assertIn((page_two_url, "text/html,application/xhtml+xml"), client.calls)
        self.assertEqual(len(connector.last_reports[0].pages), 2)

    def test_onclick_only_pagination_is_discovered_in_segments(self):
        page_two_url = OFFICIAL_ROOT + "I_list_002_20260807.html"
        page_three_url = OFFICIAL_ROOT + "I_list_003_20260807.html"
        first = (
            '<html><body><p>全 3 件</p>'
            '<button onClick="pagerLink(\'I_list_002_20260807.html\')">次頁</button>'
            f'<table>{row("1111", suffix="a")}</table></body></html>'
        ).encode()
        second = (
            '<html><body>'
            '<span data-action="pagerLink(\'I_list_003_20260807.html\')">次頁</span>'
            f'<table>{row("2222", at="10:00", suffix="b")}</table>'
            '</body></html>'
        ).encode()
        third = (
            f'<html><body><table>{row("3333", at="11:00", suffix="c")}'
            '</table></body></html>'
        ).encode()
        connector, client = connector_for(
            first,
            crosscheck(
                crosscheck_record("1111", "決算短信", "2026-08-07 09:00:00"),
                crosscheck_record("2222", "決算短信", "2026-08-07 10:00:00"),
                crosscheck_record("3333", "決算短信", "2026-08-07 11:00:00"),
            ),
            responses={page_two_url: second, page_three_url: third},
        )

        items = connector.collect(request("1111", "2222", "3333"))

        self.assertEqual(
            [item.tickers[0] for item in items],
            ["1111", "2222", "3333"],
        )
        self.assertEqual(len(connector.last_reports[0].pages), 3)
        self.assertTrue(connector.last_reports[0].pages_contiguous)
        self.assertIn(
            (page_three_url, "text/html,application/xhtml+xml"),
            client.calls,
        )

    def test_onclick_external_host_is_reduced_to_official_local_page(self):
        page_two_url = OFFICIAL_ROOT + "I_list_002_20260807.html"
        first = (
            '<html><body><p>全 2 件</p>'
            '<button onclick="pagerLink(\'https://evil.example/'
            'I_list_002_20260807.html\')">次頁</button>'
            f'<table>{row("1111", suffix="a")}</table></body></html>'
        ).encode()
        second = (
            f'<html><body><table>{row("2222", at="10:00", suffix="b")}'
            '</table></body></html>'
        ).encode()
        connector, client = connector_for(
            first,
            crosscheck(
                crosscheck_record("1111", "決算短信", "2026-08-07 09:00:00"),
                crosscheck_record("2222", "決算短信", "2026-08-07 10:00:00"),
            ),
            responses={page_two_url: second},
        )

        connector.collect(request("1111", "2222"))

        self.assertFalse(any("evil.example" in url for url, _ in client.calls))

    def test_onclick_pagination_for_a_different_day_is_not_followed(self):
        different_day = OFFICIAL_ROOT + "I_list_002_20260808.html"
        first = (
            '<html><body><p>全 1 件</p>'
            '<button onclick="pagerLink(\'I_list_002_20260808.html\')">翌日</button>'
            f'<table>{row("1111")}</table></body></html>'
        ).encode()
        connector, client = connector_for(
            first,
            crosscheck(crosscheck_record()),
            responses={different_day: page(0)},
        )

        items = connector.collect(request("1111"))

        self.assertEqual(len(items), 1)
        self.assertFalse(any(url == different_day for url, _ in client.calls))

    def test_onclick_page_number_gap_fails_closed(self):
        page_three_url = OFFICIAL_ROOT + "I_list_003_20260807.html"
        first = (
            '<html><body><p>全 2 件</p>'
            '<button onclick="pagerLink(\'I_list_003_20260807.html\')">次頁</button>'
            f'<table>{row("1111")}</table></body></html>'
        ).encode()
        third = (
            f'<html><body><table>{row("2222", at="10:00", suffix="b")}'
            '</table></body></html>'
        ).encode()
        connector, _ = connector_for(
            first,
            crosscheck(),
            responses={page_three_url: third},
        )

        with self.assertRaisesRegex(TDnetDataError, "not contiguous"):
            connector.collect(request("1111", "2222"))
        self.assertEqual(connector.last_reports[0].status, TDnetCompleteness.PARTIAL)
        self.assertFalse(connector.last_reports[0].pages_contiguous)

    def test_missing_required_row_field_fails_closed(self):
        incomplete = "<html><body><p>全 1 件</p><table><tr><td>09:00</td><td>1111</td><td>PDFなし</td></tr></table></body></html>".encode()
        connector, _ = connector_for(incomplete, crosscheck())
        with self.assertRaisesRegex(TDnetDataError, "declared=1 parsed=0"):
            connector.collect(request("1111"))
        self.assertEqual(connector.last_reports[0].status, TDnetCompleteness.PARTIAL)

    def test_absent_declared_count_fails_closed(self):
        connector, _ = connector_for(b"<html><body><table>" + row().encode() + b"</table></body></html>", crosscheck())
        with self.assertRaisesRegex(TDnetDataError, "completeness is unknown"):
            connector.collect(request("1111"))

    def test_duplicate_rows_are_deduplicated_before_count_check(self):
        duplicate = row()
        connector, _ = connector_for(page(1, duplicate, duplicate), crosscheck(crosscheck_record()))
        items = connector.collect(request("1111"))
        self.assertEqual(len(items), 1)

    def test_yanoshin_difference_requires_reconciliation(self):
        connector, _ = connector_for(
            page(1, row()),
            crosscheck(crosscheck_record(), crosscheck_record("2222", "未取得公告", "2026-08-07 10:00:00")),
        )
        with self.assertRaisesRegex(TDnetCollectionError, "reconciliation required"):
            connector.collect(request("1111"))
        report = connector.last_reports[0]
        self.assertEqual(report.status, TDnetCompleteness.RECONCILIATION_REQUIRED)
        self.assertEqual(len(report.missing_from_official), 1)

    def test_duplicate_comparison_key_count_missing_official_fails(self):
        connector, _ = connector_for(
            page(1, row(suffix="official-one")),
            crosscheck(
                crosscheck_record(),
                {
                    **crosscheck_record(),
                    "document_url": "https://crosscheck.example.test/second.pdf",
                },
            ),
        )

        with self.assertRaisesRegex(
            TDnetCollectionError,
            "reconciliation required",
        ):
            connector.collect(request("1111"))

        report = connector.last_reports[0]
        self.assertEqual(len(report.missing_from_official), 1)
        self.assertEqual(
            report.status,
            TDnetCompleteness.RECONCILIATION_REQUIRED,
        )

    def test_duplicate_comparison_key_counts_match_when_both_have_two(self):
        connector, _ = connector_for(
            page(
                2,
                row(suffix="official-one"),
                row(suffix="official-two"),
            ),
            crosscheck(
                crosscheck_record(),
                {
                    **crosscheck_record(),
                    "document_url": "https://crosscheck.example.test/second.pdf",
                },
            ),
        )

        items = connector.collect(request("1111"))

        self.assertEqual(len(items), 2)
        self.assertEqual(
            connector.last_reports[0].missing_from_official,
            (),
        )

    def test_official_duplicate_count_more_fails_closed_and_records_difference(self):
        connector, _ = connector_for(
            page(
                2,
                row(suffix="official-one"),
                row(suffix="official-two"),
            ),
            crosscheck(crosscheck_record()),
        )

        with self.assertRaisesRegex(
            TDnetCollectionError,
            "reconciliation required",
        ):
            connector.collect(request("1111"))

        report = connector.last_reports[0]
        self.assertEqual(report.official_count, 2)
        self.assertEqual(report.status, TDnetCompleteness.RECONCILIATION_REQUIRED)
        self.assertEqual(report.missing_from_official, ())
        self.assertEqual(
            report.missing_from_crosscheck,
            (("1111", "2026-08-07T09:00", "決算短信"),),
        )

    def test_counter_differences_are_preserved_in_ledger_json(self):
        with TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.jsonl"
            connector, _ = connector_for(
                page(
                    2,
                    row(suffix="official-one"),
                    row(suffix="official-two"),
                ),
                crosscheck(
                    crosscheck_record(),
                    crosscheck_record(
                        "2222",
                        "第三方のみ",
                        "2026-08-07 10:00:00",
                    ),
                ),
                ledger_path=ledger,
            )

            with self.assertRaisesRegex(
                TDnetCollectionError,
                "reconciliation required",
            ):
                connector.collect(request("1111"))

            payload = json.loads(
                ledger.read_text(encoding="utf-8").splitlines()[-1]
            )
            self.assertEqual(payload["status"], "reconciliation_required")
            self.assertEqual(payload["missing_from_official"], [
                ["2222", "2026-08-07T10:00", "第三方のみ"],
            ])
            self.assertEqual(payload["missing_from_crosscheck"], [
                ["1111", "2026-08-07T09:00", "決算短信"],
            ])

    def test_yanoshin_unavailable_fails_closed(self):
        connector, _ = connector_for(
            page(1, row()),
            TDnetCollectionError("cross-check timeout"),
        )
        with self.assertRaisesRegex(TDnetCollectionError, "cross-check unavailable"):
            connector.collect(request("1111"))
        self.assertEqual(connector.last_reports[0].status, TDnetCompleteness.UNKNOWN)

    def test_source_wide_collection_filters_only_after_full_parse(self):
        connector, client = connector_for(
            page(2, row("1111", suffix="a"), row("2222", title="対象外公告", at="10:00", suffix="b")),
            crosscheck(
                crosscheck_record("1111", "決算短信", "2026-08-07 09:00:00"),
                crosscheck_record("2222", "対象外公告", "2026-08-07 10:00:00"),
            ),
        )
        items = connector.collect(request("1111", markets={"1111": "jp"}))
        self.assertEqual([item.tickers for item in items], [("1111",)])
        self.assertEqual(connector.last_reports[0].official_count, 2)
        self.assertEqual(len(client.calls), 2)

    def test_checkpoint_advances_only_after_complete_success(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            failed, _ = connector_for(
                page(1, row()),
                crosscheck(crosscheck_record("2222", "缺失", "2026-08-07 10:00:00")),
                checkpoint_path=checkpoint,
            )
            with self.assertRaises(TDnetCollectionError):
                failed.collect(request("1111"))
            failed.commit_checkpoint()
            self.assertFalse(checkpoint.exists())

            complete, _ = connector_for(
                page(1, row()),
                crosscheck(crosscheck_record()),
                checkpoint_path=checkpoint,
                now=lambda: datetime(2026, 8, 8, 12, tzinfo=timezone.utc),
            )
            complete.collect(request("1111"))
            complete.commit_checkpoint()
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(payload["last_complete_date"], "2026-08-07")
            self.assertEqual(payload["status"], "complete")

    def test_checkpoint_overlap_does_not_expand_the_clamped_request_start(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            checkpoint.write_text(json.dumps({
                "source": "tdnet_public_web",
                "last_complete_date": "2026-08-07",
                "status": "complete",
            }), encoding="utf-8")
            responses = {}
            for day_text in ("20260806", "20260807"):
                responses[OFFICIAL_ROOT + f"I_list_001_{day_text}.html"] = page(0)
                responses[yanoshin_url(day_text)] = crosscheck()
            client = FakeClient(responses)
            connector = TDnetConnector(
                client,
                official_base_url=OFFICIAL_ROOT,
                yanoshin_base_url=YANOSHIN_ROOT,
                checkpoint_path=checkpoint,
                now=lambda: datetime(2026, 8, 8, 12, tzinfo=timezone.utc),
            )

            connector.collect(request("1111"))

            official_urls = [url for url, _ in client.calls if "official" in url]
            self.assertEqual(official_urls, [
                OFFICIAL_ROOT + "I_list_001_20260807.html",
            ])

    def test_expired_checkpoint_fails_stale_before_network(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            checkpoint.write_text(json.dumps({
                "source": "tdnet_public_web",
                "last_complete_date": "2026-08-07",
                "status": "complete",
            }), encoding="utf-8")
            client = FakeClient({})
            connector = TDnetConnector(
                client,
                official_base_url=OFFICIAL_ROOT,
                yanoshin_base_url=YANOSHIN_ROOT,
                checkpoint_path=checkpoint,
                now=lambda: datetime(2026, 9, 10, 12, tzinfo=timezone.utc),
            )
            stale_request = CollectionRequest(
                tickers=("1111",),
                start_date=date(2026, 9, 9),
                end_date=date(2026, 9, 9),
                markets={"1111": "jp"},
            )

            with self.assertRaisesRegex(
                TDnetDataError,
                "historical_gap_requires_backfill",
            ):
                connector.collect(stale_request)

            self.assertEqual(client.calls, [])
            self.assertEqual(connector.last_reports[0].status, TDnetCompleteness.STALE)
            self.assertEqual(
                connector.last_reports[0].message,
                "historical_gap_requires_backfill",
            )

    def test_corrupt_checkpoint_fails_closed_before_network(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            checkpoint.write_text("not-json", encoding="utf-8")
            connector, client = connector_for(
                page(0),
                crosscheck(),
                checkpoint_path=checkpoint,
                now=lambda: datetime(2026, 8, 8, 12, tzinfo=timezone.utc),
            )

            with self.assertRaisesRegex(TDnetDataError, "checkpoint is corrupt"):
                connector.collect(request("1111"))
            self.assertEqual(client.calls, [])

    def test_title_change_keeps_logical_id_and_stores_two_immutable_versions(self):
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / "items.sqlite3"
            repository = SQLiteInformationRepository(database_path)
            first, _ = connector_for(
                page(1, row(title="初回タイトル", suffix="stable")),
                crosscheck(crosscheck_record(title="初回タイトル")),
                now=lambda: datetime(2026, 8, 8, 12, tzinfo=timezone.utc),
            )
            second, _ = connector_for(
                page(1, row(title="訂正タイトル", suffix="stable")),
                crosscheck(crosscheck_record(title="訂正タイトル")),
                now=lambda: datetime(2026, 8, 8, 13, tzinfo=timezone.utc),
            )

            first_item = first.collect(request("1111"))[0]
            second_item = second.collect(request("1111"))[0]
            repository.save([first_item])
            repository.save([second_item])

            self.assertEqual(first_item.external_id, second_item.external_id)
            self.assertNotEqual(
                first_item.raw_metadata["raw_content_hash"],
                second_item.raw_metadata["raw_content_hash"],
            )
            self.assertEqual(repository.count(), 1)
            with sqlite3.connect(str(database_path)) as connection:
                versions = connection.execute(
                    "SELECT payload FROM information_item_versions ORDER BY id"
                ).fetchall()
            self.assertEqual(len(versions), 2)
            self.assertEqual(
                [json.loads(payload)["title"] for payload, in versions],
                ["初回タイトル", "訂正タイトル"],
            )

    def test_current_japanese_day_never_writes_complete_checkpoint(self):
        with TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            connector, _ = connector_for(
                page(1, row()),
                crosscheck(crosscheck_record()),
                checkpoint_path=checkpoint,
            )
            connector.collect(request("1111"))
            connector.commit_checkpoint()
            self.assertFalse(checkpoint.exists())

    def test_yanoshin_known_limit_fails_closed(self):
        connector, _ = connector_for(
            page(1, row()),
            crosscheck(*(crosscheck_record() for _ in range(3))),
            yanoshin_limit=3,
        )
        with self.assertRaisesRegex(TDnetCollectionError, "requested response limit"):
            connector.collect(request("1111"))
        report = connector.last_reports[0]
        self.assertTrue(report.crosscheck_truncated)
        self.assertEqual(report.status, TDnetCompleteness.UNKNOWN)

    def test_yanoshin_real_wrapper_and_explicit_limit_are_validated(self):
        wrapper = json.dumps({
            "items": [{"Tdnet": crosscheck_record()}],
            "total_count": 1,
            "actions": {},
            "condition_desc": "fixture",
        }, ensure_ascii=False).encode()
        connector, client = connector_for(page(1, row()), wrapper)

        connector.collect(request("1111"))

        self.assertIn((yanoshin_url(), "application/json"), client.calls)
        report = connector.last_reports[0]
        self.assertEqual(report.crosscheck_requested_limit, DEFAULT_LIMIT)
        self.assertEqual(report.crosscheck_reported_total, 1)
        self.assertEqual(
            report.crosscheck_coverage,
            "wrapper_count_matches_below_requested_limit",
        )

    def test_yanoshin_wrapper_count_mismatch_fails_closed(self):
        wrapper = json.dumps({
            "items": [crosscheck_record()],
            "total_count": 2,
            "actions": {},
            "condition_desc": "fixture",
        }, ensure_ascii=False).encode()
        connector, _ = connector_for(page(1, row()), wrapper)

        with self.assertRaisesRegex(TDnetCollectionError, "total_count"):
            connector.collect(request("1111"))
        self.assertEqual(
            connector.last_reports[0].status,
            TDnetCompleteness.UNKNOWN,
        )
        self.assertEqual(connector.last_reports[0].crosscheck_reported_total, 2)
        self.assertEqual(
            connector.last_reports[0].crosscheck_coverage,
            "reported_total_mismatch",
        )

    def test_yanoshin_wrapper_rejects_invalid_total_count_types(self):
        for invalid_total in ("1", True, -1, None):
            with self.subTest(total_count=invalid_total):
                wrapper = json.dumps({
                    "items": [{"Tdnet": crosscheck_record()}],
                    "total_count": invalid_total,
                }, ensure_ascii=False).encode()
                connector, _ = connector_for(page(1, row()), wrapper)

                with self.assertRaisesRegex(
                    TDnetCollectionError,
                    "non-negative integer",
                ):
                    connector.collect(request("1111"))
                self.assertEqual(
                    connector.last_reports[0].crosscheck_coverage,
                    "invalid_reported_total",
                )

    def test_yanoshin_wrapper_at_requested_limit_fails_closed(self):
        records = [
            {"Tdnet": crosscheck_record(str(1111 + offset))}
            for offset in range(3)
        ]
        wrapper = json.dumps({
            "items": records,
            "total_count": 3,
        }, ensure_ascii=False).encode()
        connector, _ = connector_for(
            page(1, row()),
            wrapper,
            yanoshin_limit=3,
        )

        with self.assertRaisesRegex(TDnetCollectionError, "requested response limit"):
            connector.collect(request("1111"))
        report = connector.last_reports[0]
        self.assertTrue(report.crosscheck_truncated)
        self.assertEqual(report.crosscheck_reported_total, 3)
        self.assertEqual(report.crosscheck_requested_limit, 3)

    def test_yanoshin_legacy_list_remains_compatible(self):
        connector, _ = connector_for(
            page(1, row()),
            crosscheck({"Tdnet": crosscheck_record()}),
        )

        items = connector.collect(request("1111"))

        self.assertEqual(len(items), 1)
        self.assertEqual(
            connector.last_reports[0].crosscheck_coverage,
            "legacy_list_fixture_no_reported_total",
        )

    def test_environment_requires_explicit_public_page_permission(self):
        with patch.dict(
            "os.environ",
            {
                "TDNET_USER_AGENT": "InvestmentMonitor test@example.test",
                "TDNET_PUBLIC_PAGE_PERMISSION_CONFIRMED": "false",
            },
            clear=False,
        ):
            self.assertIn("PERMISSION_CONFIRMED", TDnetConnector.configuration_error())
            with self.assertRaises(ConnectorUnavailableError):
                TDnetConnector.from_environment()

    def test_environment_builds_only_after_permission_is_confirmed(self):
        with patch.dict(
            "os.environ",
            {
                "TDNET_USER_AGENT": "InvestmentMonitor test@example.test",
                "TDNET_PUBLIC_PAGE_PERMISSION_CONFIRMED": "true",
                "TDNET_CHECKPOINT_PATH": "",
                "TDNET_LEDGER_PATH": "",
                "TDNET_YANOSHIN_LIMIT": "17",
            },
            clear=True,
        ):
            connector = TDnetConnector.from_environment()
            self.assertIsNone(TDnetConnector.configuration_error())

        self.assertIsInstance(connector, TDnetConnector)

    def test_supported_ticker_suffixes_match_official_company_code(self):
        for ticker in ("1111", "1111.T", "1111:JP"):
            with self.subTest(ticker=ticker):
                connector, _ = connector_for(
                    page(1, row()),
                    crosscheck(crosscheck_record()),
                )
                items = connector.collect(request(ticker))
                self.assertEqual(items[0].tickers, (ticker,))

    def test_unconfirmed_ticker_format_fails_before_network(self):
        connector, client = connector_for(page(0), crosscheck())
        with self.assertRaisesRegex(TDnetDataError, "Unresolved"):
            connector.collect(request("TYO-1111"))
        self.assertEqual(client.calls, [])


class _Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class SequencedOpener:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, request, timeout):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome)


class TDnetHTTPClientTests(unittest.TestCase):
    def make_client(self, opener, sleeps):
        return TDnetHTTPClient(
            "InvestmentMonitor test@example.test",
            public_page_permission_confirmed=True,
            timeout=1,
            max_retries=2,
            requests_per_second=1000,
            opener=opener,
            clock=lambda: 0,
            sleeper=sleeps.append,
        )

    def test_permission_capability_defaults_to_denied(self):
        with self.assertRaisesRegex(
            ConnectorUnavailableError,
            "permission capability",
        ):
            TDnetHTTPClient("InvestmentMonitor test@example.test")

    def test_retries_429_with_exponential_backoff(self):
        url = "https://official.example.test/page"
        throttled = HTTPError(url, 429, "rate limited", {}, None)
        opener = SequencedOpener(throttled, b"ok")
        sleeps = []
        client = self.make_client(opener, sleeps)
        self.assertEqual(client.get_bytes(url, "text/html"), b"ok")
        self.assertEqual(opener.calls, 2)
        self.assertIn(0.5, sleeps)

    def test_retries_timeout_and_raises_after_bound(self):
        opener = SequencedOpener(
            URLError(TimeoutError("timed out")),
            URLError(TimeoutError("timed out")),
            URLError(TimeoutError("timed out")),
        )
        sleeps = []
        client = self.make_client(opener, sleeps)
        with self.assertRaisesRegex(TDnetCollectionError, "after 3 attempts"):
            client.get_bytes("https://official.example.test/page", "text/html")
        self.assertEqual(opener.calls, 3)
        self.assertIn(0.5, sleeps)
        self.assertIn(1.0, sleeps)


if __name__ == "__main__":
    unittest.main()
