"""Regression tests for the independent, broker-free product boundary."""

import importlib.util
import unittest

import investment_monitor
from investment_monitor import universe
from investment_monitor.web_repository import WebRepository


class NoBrokerRuntimeTests(unittest.TestCase):
    def test_broker_contract_modules_are_not_packaged(self):
        self.assertIsNone(
            importlib.util.find_spec("investment_monitor.universe.ibkr_secdef")
        )
        self.assertIsNone(
            importlib.util.find_spec("investment_monitor.universe.ibkr_reference")
        )

    def test_broker_contract_api_is_not_exported(self):
        for module in (investment_monitor, universe):
            self.assertFalse(hasattr(module, "search_contracts"))
            self.assertFalse(hasattr(module, "ibkr_conid_for"))
        self.assertFalse(hasattr(WebRepository, "set_company_ibkr_contract"))
        self.assertFalse(hasattr(WebRepository, "company_ibkr_contract"))


if __name__ == "__main__":
    unittest.main()
