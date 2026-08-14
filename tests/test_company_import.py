"""Pure parsing tests for the ``TICKER.MARKET`` mixed batch-add format."""

from __future__ import annotations

import unittest

from investment_monitor.company_import import (
    group_by_market,
    market_for_suffix,
    parse_company_inputs,
    split_tokens,
)


def pairs(parsed):
    return [(item.ticker, item.market) for item in parsed]


class CompanyImportParseTests(unittest.TestCase):
    def test_splits_on_all_separators(self):
        self.assertEqual(
            split_tokens(
                "AAPL.US, MSFT.US 0700.HK；005930.KR;7203.T\n2330.TW，RY.TO"
            ),
            [
                "AAPL.US",
                "MSFT.US",
                "0700.HK",
                "005930.KR",
                "7203.T",
                "2330.TW",
                "RY.TO",
            ],
        )

    def test_canonical_suffixes(self):
        self.assertEqual(
            pairs(parse_company_inputs("AAPL.US", "us")), [("AAPL", "us")]
        )
        self.assertEqual(
            pairs(parse_company_inputs("0700.HK", "us")), [("0700", "hk")]
        )
        self.assertEqual(
            pairs(parse_company_inputs("005930.KR", "us")), [("005930", "kr")]
        )

    def test_alias_suffixes(self):
        cases = {
            "RY.TO": ("RY", "ca"),
            "BHP.AX": ("BHP", "au"),
            "VOD.L": ("VOD", "uk"),
            "005930.KS": ("005930", "kr"),
            "7203.T": ("7203", "jp"),
            "600519.SS": ("600519", "cn"),
            "000001.SZ": ("000001", "cn"),
            "SAN.MC": ("SAN", "es"),
            "NESN.SW": ("NESN", "ch"),
            "D05.SI": ("D05", "sg"),
            "PKO.WA": ("PKO", "pl"),
            "ERIC-B.ST": ("ERIC-B", "se"),
            "VOD.LSE": ("VOD", "uk"),
            "600519.SH": ("600519", "cn"),
            "ASML.AS": ("ASML", "nl"),
            "ENI.MI": ("ENI", "it"),
            "SAP.F": ("SAP", "de"),
            "SAP.XETRA": ("SAP", "de"),
            "AAA.AQSE": ("AAA", "aq"),
            "AZN.BXE": ("AZN", "cxe"),
            "AZN.TRQX": ("AZN", "trq"),
        }
        for token, (ticker, market) in cases.items():
            with self.subTest(token=token):
                self.assertEqual(
                    pairs(parse_company_inputs(token, "us")), [(ticker, market)]
                )

    def test_case_insensitive(self):
        self.assertEqual(
            pairs(parse_company_inputs("aapl.us", "us")), [("aapl", "us")]
        )
        self.assertEqual(pairs(parse_company_inputs("ry.to", "us")), [("ry", "ca")])
        self.assertEqual(
            pairs(parse_company_inputs("0700.hk", "us")), [("0700", "hk")]
        )

    def test_at_suffix_format(self):
        cases = {
            "AAPL@US": ("AAPL", "us"),
            "0700@HK": ("0700", "hk"),
            "7203@JP": ("7203", "jp"),
            "RY@CA": ("RY", "ca"),
            "BHP@AU": ("BHP", "au"),
            "005930@KS": ("005930", "kr"),
            "600519@SS": ("600519", "cn"),
            "NESN@SW": ("NESN", "ch"),
        }
        for token, (ticker, market) in cases.items():
            with self.subTest(token=token):
                self.assertEqual(
                    pairs(parse_company_inputs(token, "us")), [(ticker, market)]
                )

    def test_at_suffix_is_case_insensitive(self):
        self.assertEqual(
            pairs(parse_company_inputs("aapl@us", "us")), [("aapl", "us")]
        )
        self.assertEqual(
            pairs(parse_company_inputs("0700@hk", "us")), [("0700", "hk")]
        )

    def test_at_suffix_prefers_at_over_dot(self):
        # ``@`` wins when both appear: the internal dot stays inside the ticker.
        self.assertEqual(
            pairs(parse_company_inputs("BRK.B@US", "us")), [("BRK.B", "us")]
        )

    def test_at_suffix_unknown_is_kept_as_ticker(self):
        self.assertEqual(
            pairs(parse_company_inputs("ABC@XYZ", "us")), [("ABC@XYZ", "us")]
        )

    def test_at_suffix_dedupes_against_dot_form(self):
        self.assertEqual(
            pairs(parse_company_inputs("AAPL@US AAPL.US AAPL", "us")),
            [("AAPL", "us")],
        )

    def test_mixed_at_and_dot_separators(self):
        self.assertEqual(
            pairs(parse_company_inputs("AAPL@US 0700.HK 7203@JP RY.TO", "us")),
            [("AAPL", "us"), ("0700", "hk"), ("7203", "jp"), ("RY", "ca")],
        )

    def test_ticker_with_internal_dot_is_protected(self):
        self.assertEqual(
            pairs(parse_company_inputs("BRK.B", "us")), [("BRK.B", "us")]
        )
        self.assertEqual(
            pairs(parse_company_inputs("BF.B", "us")), [("BF.B", "us")]
        )

    def test_mixed_input_uses_default_market_for_plain_tickers(self):
        self.assertEqual(
            pairs(parse_company_inputs("AAPL.US BRK.B 0700.HK RY.TO", "us")),
            [("AAPL", "us"), ("BRK.B", "us"), ("0700", "hk"), ("RY", "ca")],
        )

    def test_unknown_suffix_is_kept_as_ticker(self):
        self.assertEqual(
            pairs(parse_company_inputs("ABC.XYZ", "us")), [("ABC.XYZ", "us")]
        )
        # A single-letter suffix that is not in the allowlist stays inside the
        # ticker (BRK.B-style protection is not special-cased for ".B").
        self.assertEqual(
            pairs(parse_company_inputs("BRK.Z", "us")), [("BRK.Z", "us")]
        )

    def test_dedupe_by_ticker_and_market(self):
        self.assertEqual(
            pairs(parse_company_inputs("AAPL.US AAPL.US AAPL", "us")),
            [("AAPL", "us")],
        )
        self.assertEqual(
            pairs(parse_company_inputs("ABC.US ABC.HK", "us")),
            [("ABC", "us"), ("ABC", "hk")],
        )

    def test_empty_and_separator_only_input(self):
        self.assertEqual(parse_company_inputs("", "us"), [])
        self.assertEqual(parse_company_inputs("  , ; ， ； \n ", "us"), [])

    def test_group_by_market_preserves_order(self):
        parsed = parse_company_inputs("AAPL.US 0700.HK RY.TO MSFT.US", "us")
        groups = group_by_market(parsed)
        self.assertEqual(
            [(market, [item.ticker for item in items]) for market, items in groups],
            [("us", ["AAPL", "MSFT"]), ("hk", ["0700"]), ("ca", ["RY"])],
        )

    def test_market_for_suffix(self):
        self.assertIsNone(market_for_suffix("xyz"))
        self.assertIsNone(market_for_suffix("b"))
        self.assertIsNone(market_for_suffix("unknown"))
        self.assertEqual(market_for_suffix("TO"), "ca")
        self.assertEqual(market_for_suffix("to"), "ca")


if __name__ == "__main__":
    unittest.main()
