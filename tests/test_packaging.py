"""Packaging guard: the catalog seed JSON must ship inside wheels."""

from pathlib import Path
import unittest


class PackagingTests(unittest.TestCase):
    def test_catalog_json_is_declared_as_package_data(self):
        pyproject = Path(__file__).parents[1] / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8")
        self.assertIn('universe/*.json', text)
        seed = (
            Path(__file__).parents[1]
            / "src" / "investment_monitor" / "universe"
            / "ibkr_exchange_catalog.json"
        )
        self.assertTrue(seed.exists())


if __name__ == "__main__":
    unittest.main()
