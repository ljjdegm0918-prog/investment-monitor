"""Regression tests for the web UI English/Chinese language toggle.

Covers both the static app.js bundle (mechanism present, translations present,
external data preserved) and the runtime language-detection/priority behaviour
via a Node sandbox (``tests/test_i18n.js``).
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import unittest

from investment_monitor.web import WebApplication


APP_JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "investment_monitor"
    / "web_static"
    / "app.js"
)


class WebI18nStaticTests(unittest.TestCase):
    def _app_js(self) -> str:
        return APP_JS_PATH.read_text(encoding="utf-8")

    def test_app_js_has_i18n_mechanism(self) -> None:
        js = self._app_js()
        for token in (
            "SUPPORTED_LANGS",
            "MESSAGES",
            "function t(",
            "detectLang",
            "toggleLang",
            "lang-toggle",
            "LANG_STORAGE_KEY",
            "localeFor",
        ):
            self.assertIn(token, js)

    def test_app_js_has_chinese_translations(self) -> None:
        js = self._app_js()
        for zh in (
            "每日报告",
            "生成报告",
            "新闻",
            "社区",
            "已连接",
            "列表与来源",
            "打印 / 保存 PDF",
            "官方披露",
        ):
            self.assertIn(zh, js)

    def test_app_js_preserves_external_identifiers(self) -> None:
        # Tickers must never be translated. Source ids and brand names are now
        # served by /api/sources and rendered verbatim (never through the i18n
        # table), so they no longer need to be hardcoded in app.js.
        js = self._app_js()
        for token in (
            "AAPL",
            "0700",
            "RY",
            "BRK.B",
        ):
            self.assertIn(token, js)

    def test_app_js_no_longer_hardcodes_english_labels(self) -> None:
        # Labels that moved into MESSAGES should no longer appear as raw
        # template-literal UI text (only as translation dictionary values).
        js = self._app_js()
        self.assertNotIn(">Print / Save PDF<", js)
        self.assertNotIn(">Generate reports<", js)


class WebI18nRuntimeTests(unittest.TestCase):
    def test_language_priority_and_fallback(self) -> None:
        result = subprocess.run(
            ["node", "tests/test_i18n.js"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("i18n tests passed", result.stdout)


class WebI18nServerTests(unittest.TestCase):
    """The served app.js bundle exposes the toggle entry and translations."""

    def setUp(self) -> None:
        from tempfile import TemporaryDirectory
        from investment_monitor.application import ConfiguredCollectionResult
        from investment_monitor.repository import SaveResult

        self.temporary_directory = TemporaryDirectory()
        project_root = Path(self.temporary_directory.name)
        (project_root / "config").mkdir()
        (project_root / "data").mkdir()
        (project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\n  - news\n  - community\n"
            "database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        (project_root / "config" / "universe.csv").write_text(
            "ticker,list_type\nAAPL,holdings\n", encoding="utf-8"
        )
        cache = project_root / ".cache" / "investment_monitor"
        cache.mkdir(parents=True)
        (cache / "company_tickers.json").write_text("{}", encoding="utf-8")

        def noop(**kwargs):
            return ConfiguredCollectionResult(
                items=(),
                failures=(),
                save_result=SaveResult(),
                database_path=project_root / "data" / "web.sqlite3",
                stored_count=0,
            )

        self.application = WebApplication(
            project_root,
            collection_runner=noop,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_served_app_js_has_language_toggle(self) -> None:
        response = self.application.handle("GET", "/static/app.js")
        self.assertEqual(response.status, 200)
        self.assertIn(b"lang-toggle", response.body)
        self.assertIn(b"zh-CN", response.body)
        self.assertIn(b"MESSAGES", response.body)

    def test_today_page_serves_without_lang(self) -> None:
        response = self.application.handle("GET", "/today")
        self.assertEqual(response.status, 200)
        # The HTML shell defaults to English.
        self.assertIn(b'lang="en"', response.body)
        self.assertIn(b"Daily information", response.body)

    def test_today_page_serves_zh_lang(self) -> None:
        response = self.application.handle("GET", "/today?lang=zh-CN")
        self.assertEqual(response.status, 200)
        self.assertIn(b"Investment Monitor", response.body)


if __name__ == "__main__":
    unittest.main()
