"""DE-1: DAX 40 seed companies through the batch add path.

The 40 constituent tickers below are the canonical DAX 40 roster with the
``.DE`` exchange suffix as delivered by data providers. Each raw ticker is
normalized via ``normalize_de_ticker`` and added through
``WebRepository.add_companies_batch(market="de")`` exactly like the FR-1
batch-add flow, with a name fallback map holding the full legal names so the
database never stores bare tickers as display names.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import SQLiteInformationRepository, WebRepository
from investment_monitor.web_repository import normalize_de_ticker

DAX40_TICKERS = (
    "ADS.DE",
    "AIR.DE",
    "ALV.DE",
    "BAS.DE",
    "BAYN.DE",
    "BMW.DE",
    "BNR.DE",
    "CBK.DE",
    "CON.DE",
    "DB1.DE",
    "DBK.DE",
    "DHER.DE",
    "DPW.DE",
    "DTE.DE",
    "ENR.DE",
    "EOAN.DE",
    "FME.DE",
    "FRE.DE",
    "HEI.DE",
    "HEN3.DE",
    "HNR1.DE",
    "IFX.DE",
    "MBG.DE",
    "MRK.DE",
    "MTX.DE",
    "MUV2.DE",
    "PAH3.DE",
    "PUM.DE",
    "QIA.DE",
    "RHM.DE",
    "RWE.DE",
    "SAP.DE",
    "SHL.DE",
    "SIE.DE",
    "SRZ.DE",
    "SY1.DE",
    "VNA.DE",
    "VOW3.DE",
    "WDI.DE",
    "ZAL.DE",
)

DAX40_NAMES = {
    "ADS": "adidas AG",
    "AIR": "Airbus SE",
    "ALV": "Allianz SE",
    "BAS": "BASF SE",
    "BAYN": "Bayer AG",
    "BMW": "BMW AG",
    "BNR": "Brenntag SE",
    "CBK": "Commerzbank AG",
    "CON": "Continental AG",
    "DB1": "Deutsche Börse AG",
    "DBK": "Deutsche Bank AG",
    "DHER": "Delivery Hero SE",
    "DPW": "Deutsche Post AG (DHL Group)",
    "DTE": "Deutsche Telekom AG",
    "ENR": "Siemens Energy AG",
    "EOAN": "E.ON SE",
    "FME": "Fresenius Medical Care AG",
    "FRE": "Fresenius SE & Co. KGaA",
    "HEI": "Heidelberg Materials AG",
    "HEN3": "Henkel AG & Co. KGaA",
    "HNR1": "Hannover Rück SE",
    "IFX": "Infineon Technologies AG",
    "MBG": "Mercedes-Benz Group AG",
    "MRK": "Merck KGaA",
    "MTX": "MTU Aero Engines AG",
    "MUV2": "Münchener Rückversicherungs-Gesellschaft AG",
    "PAH3": "Porsche Automobil Holding SE",
    "PUM": "Puma SE",
    "QIA": "Qiagen N.V.",
    "RHM": "Rheinmetall AG",
    "RWE": "RWE AG",
    "SAP": "SAP SE",
    "SHL": "Siemens Healthineers AG",
    "SIE": "Siemens AG",
    "SRZ": "Sartorius AG",
    "SY1": "Symrise AG",
    "VNA": "Vonovia SE",
    "VOW3": "Volkswagen AG",
    "WDI": "Wienerberger AG",
    "ZAL": "Zalando SE",
}

DAX40_NAME_FALLBACK = {
    root: {"name": name, "exchange": "XETRA"}
    for root, name in DAX40_NAMES.items()
}

DAX40_RAW = ", ".join(DAX40_TICKERS)


class MarketDEDax40ListTests(unittest.TestCase):
    def test_dax40_has_40_distinct_members(self) -> None:
        self.assertEqual(len(DAX40_TICKERS), 40)
        self.assertEqual(len(set(DAX40_TICKERS)), 40)
        self.assertEqual(len(DAX40_NAMES), 40)

    def test_dax40_tickers_normalize_to_fallback_keys(self) -> None:
        for raw_ticker in DAX40_TICKERS:
            root = normalize_de_ticker(raw_ticker)
            self.assertIn(root, DAX40_NAMES)
            self.assertEqual(root, raw_ticker.split(".")[0])

    def test_dax40_names_are_complete(self) -> None:
        for root, name in DAX40_NAMES.items():
            with self.subTest(root=root):
                self.assertTrue(name)
                self.assertNotEqual(name, root)


class MarketDEDax40AddTests(unittest.TestCase):
    def test_add_companies_batch_adds_all_dax40(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                DAX40_RAW,
                ("holdings",),
                None,
                market="de",
                name_fallback=DAX40_NAME_FALLBACK,
            )
            companies = repository.companies()

        self.assertEqual(result["failed"], [])
        self.assertEqual(len(result["added"]), 40)
        self.assertEqual(
            {record["ticker"] for record in result["added"]},
            set(DAX40_NAMES),
        )
        self.assertEqual(len(companies), 40)
        for record in result["added"]:
            with self.subTest(ticker=record["ticker"]):
                self.assertEqual(record["market"], "de")
                self.assertEqual(record["mapping_status"], "unmapped")
                self.assertEqual(record["cik"], "")
                self.assertEqual(
                    record["name"],
                    DAX40_NAMES[record["ticker"]],
                )

    def test_add_companies_batch_is_idempotent_for_dax40(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            repository.add_companies_batch(
                DAX40_RAW,
                ("holdings",),
                None,
                market="de",
                name_fallback=DAX40_NAME_FALLBACK,
            )
            repeated = repository.add_companies_batch(
                DAX40_RAW,
                ("holdings",),
                None,
                market="de",
                name_fallback=DAX40_NAME_FALLBACK,
            )
            companies = repository.companies()

        self.assertEqual(len(repeated["added"]), 0)
        self.assertEqual(len(repeated["already_present"]), 40)
        self.assertEqual(repeated["failed"], [])
        self.assertEqual(len(companies), 40)


if __name__ == "__main__":
    unittest.main()
