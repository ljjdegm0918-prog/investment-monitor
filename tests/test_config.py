import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from investment_monitor import (
    ConfigurationError,
    load_environment_file,
    load_settings,
    load_universe,
)


class ConfigurationTests(unittest.TestCase):
    def test_loads_supported_universe_and_settings(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            universe_path = directory / "universe.csv"
            universe_path.write_text(
                "ticker,list_type\n"
                "aapl,holdings\n"
                "MSFT,planned\n"
                "NVDA,watchlist\n",
                encoding="utf-8",
            )
            settings_path = directory / "settings.yaml"
            settings_path.write_text(
                "enabled_sources:\n"
                "  - mock\n"
                "database_path: data/items.sqlite3\n",
                encoding="utf-8",
            )

            universe = load_universe(universe_path)
            settings = load_settings(settings_path)

        self.assertEqual(
            tuple(entry.ticker for entry in universe),
            ("AAPL", "MSFT", "NVDA"),
        )
        self.assertEqual(
            tuple(entry.list_type for entry in universe),
            ("holdings", "planned", "watchlist"),
        )
        self.assertEqual(settings.enabled_sources, ("mock",))
        self.assertEqual(
            settings.database_path,
            directory / "data" / "items.sqlite3",
        )

    def test_rejects_duplicate_tickers(self) -> None:
        self.assert_invalid_csv(
            "ticker,list_type\nAAPL,holdings\naapl,watchlist\n",
            "unique",
        )

    def test_rejects_more_than_ten_tickers(self) -> None:
        rows = "".join(
            f"TICKER{index},watchlist\n" for index in range(11)
        )
        self.assert_invalid_csv(
            "ticker,list_type\n" + rows,
            "between 1 and 10",
        )

    def test_rejects_invalid_list_type(self) -> None:
        self.assert_invalid_csv(
            "ticker,list_type\nAAPL,favorite\n",
            "list_type",
        )

    def test_environment_file_loads_defaults_without_overwriting_host_values(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / ".env"
            path.write_text(
                'SEC_USER_AGENT="InvestmentMonitor/0.1 file@example.com"\n'
                "DAILY_COLLECTION_HOUR_ET=6\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"SEC_USER_AGENT": "InvestmentMonitor/0.1 host@example.com"},
                clear=True,
            ):
                load_environment_file(path)
                self.assertEqual(
                    os.environ["SEC_USER_AGENT"],
                    "InvestmentMonitor/0.1 host@example.com",
                )
                self.assertEqual(os.environ["DAILY_COLLECTION_HOUR_ET"], "6")

    def assert_invalid_csv(self, contents: str, message: str) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "universe.csv"
            path.write_text(contents, encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, message):
                load_universe(path)


if __name__ == "__main__":
    unittest.main()
