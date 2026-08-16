"""P5-3 IBKR conid enrichment tests (offline web fixture)."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from investment_monitor.web import WebApplication
from investment_monitor.application import ConfiguredCollectionResult
from investment_monitor.repository import SaveResult
from investment_monitor.web_repository import WebRepository
from investment_monitor.sqlite_repository import SQLiteInformationRepository


class _NoopRunner:
    def __init__(self, root: Path):
        self.root = root

    def __call__(self, **kwargs):
        # stored_count=0：后台回填线程不做 DB IO，避免 Windows 文件锁。
        return ConfiguredCollectionResult(
            items=(),
            failures=(),
            save_result=SaveResult(),
            database_path=self.root / "data" / "web.sqlite3",
            stored_count=0,
        )


def _application(root: Path) -> WebApplication:
    (root / "config").mkdir(exist_ok=True)
    (root / "data").mkdir(exist_ok=True)
    (root / "config" / "settings.yaml").write_text(
        "enabled_sources:\n  - sec\ndatabase_path: ../data/web.sqlite3\n",
        encoding="utf-8",
    )
    (root / "config" / "universe.csv").write_text(
        "ticker,list_type\nAAPL,holdings\n", encoding="utf-8"
    )
    cache = root / ".cache" / "investment_monitor"
    cache.mkdir(parents=True)
    (cache / "company_tickers.json").write_text(json.dumps({
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corporation"},
    }), encoding="utf-8")
    SQLiteInformationRepository(root / "data" / "web.sqlite3")
    return WebApplication(root, collection_runner=_NoopRunner(root))


class IbkrConidWebTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.application = _application(self.root)

    def test_unconfigured_add_writes_no_fake_conid(self):
        with patch(
            "investment_monitor.web.ibkr_secdef_configured",
            return_value=False,
        ) as configured:
            response = self.application.handle(
                "POST", "/api/companies/batch",
                json.dumps({
                    "tickers": "MSFT", "lists": ["holdings"], "market": "us",
                }).encode(),
            )
            configured.assert_called_once()
        self.assertEqual(response.status, 201)
        self.assertIsNone(
            self.application.repository.company_ibkr_contract("MSFT", "us")
        )

    def test_configured_add_writes_verified_conid(self):
        with patch(
            "investment_monitor.web.ibkr_secdef_configured",
            return_value=True,
        ), patch(
            "investment_monitor.web.search_contracts",
            return_value=[{
                "conid": "123456", "symbol": "MSFT",
                "primaryExchange": "NASDAQ", "currency": "USD",
            }],
        ):
            response = self.application.handle(
                "POST", "/api/companies/batch",
                json.dumps({
                    "tickers": "MSFT", "lists": ["holdings"], "market": "us",
                }).encode(),
            )
        self.assertEqual(response.status, 201)
        contract = self.application.repository.company_ibkr_contract(
            "MSFT", "us"
        )
        self.assertEqual(contract["conid"], "123456")
        self.assertEqual(contract["primary_exchange"], "NASDAQ")


class CompanyIbkrContractRepositoryTests(unittest.TestCase):
    def test_contract_roundtrip(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir(parents=True)
            (root / "data").mkdir()
            (root / "config" / "settings.yaml").write_text(
                "enabled_sources:\n  - sec\ndatabase_path: ../data/web.sqlite3\n",
                encoding="utf-8",
            )
            (root / "config" / "universe.csv").write_text(
                "ticker,list_type\nAAPL,holdings\n", encoding="utf-8"
            )
            repository = WebRepository(root / "data" / "web.sqlite3")
            repository.set_company_ibkr_contract(
                ticker="AAPL", market="us", conid="265598",
                primary_exchange="NASDAQ", currency="USD",
            )
            contract = repository.company_ibkr_contract("AAPL", "us")
            self.assertEqual(contract["conid"], "265598")
            self.assertIsNone(repository.company_ibkr_contract("AAPL", "de"))


if __name__ == "__main__":
    unittest.main()
