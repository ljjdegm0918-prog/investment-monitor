"""Scheduler-friendly CH/JP/US universe refresh entry point tests."""

import unittest

from investment_monitor.universe.daily_refresh import DailyRefreshError, run_daily_refresh


class DailyUniverseRefreshTests(unittest.TestCase):
    def test_refreshes_requested_markets_and_reports_counts(self) -> None:
        calls = []

        def refresher(name):
            def run():
                calls.append(name)
                return {
                    "updated_at": "2026-08-24T00:00:00+00:00",
                    "source_effective_date": "2026-08-23",
                    "counts": {"total": 10},
                    "coverage": f"{name}-partial",
                }
            return run

        result = run_daily_refresh(
            ("ch", "jp", "us"),
            refreshers={
                "ch": refresher("ch"),
                "jp": refresher("jp"),
                "us": refresher("us"),
            },
        )
        self.assertEqual(calls, ["ch", "jp", "us"])
        self.assertEqual(result["jp"]["counts"], {"total": 10})
        self.assertEqual(result["ch"]["source_effective_date"], "2026-08-23")
        self.assertEqual(result["us"]["coverage"], "us-partial")

    def test_failure_is_not_silently_downgraded(self) -> None:
        def broken():
            raise RuntimeError("source unavailable")

        calls = []

        def healthy():
            calls.append("jp")
            return {"counts": {"total": 8}, "coverage": "jp-partial"}

        with self.assertRaisesRegex(DailyRefreshError, "source unavailable") as caught:
            run_daily_refresh(
                ("ch", "jp"),
                refreshers={"ch": broken, "jp": healthy},
            )
        self.assertEqual(calls, ["jp"])
        self.assertEqual(caught.exception.results["jp"]["counts"], {"total": 8})


if __name__ == "__main__":
    unittest.main()
