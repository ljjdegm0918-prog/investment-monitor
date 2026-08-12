"use strict";

// Node-only test for the app.js i18n primitives (language detection priority,
// t() translation and interpolation, and safe fallback). It executes app.js
// inside a minimal browser-like sandbox so the module-level `lang` and `t`
// can be inspected without a real DOM.

const fs = require("fs");
const vm = require("vm");
const path = require("path");
const assert = require("assert");

const appJs = fs.readFileSync(
  path.join(__dirname, "..", "src", "investment_monitor", "web_static", "app.js"),
  "utf8"
);

function runApp(search, storedLang) {
  const sandbox = {
    location: { search, pathname: "/today" },
    localStorage: {
      _store: {},
      getItem(key) { return this._store[key] ?? null; },
      setItem(key, value) { this._store[key] = value; },
    },
    document: {
      documentElement: { lang: "en" },
      addEventListener() {},
      querySelector() { return null; },
      getElementById() { return null; },
    },
    URLSearchParams,
    history: { replaceState() {} },
    console,
  };
  if (storedLang) sandbox.localStorage._store["im-lang"] = storedLang;
  const code =
    appJs +
    "\n;({ lang, t, detectLang, toggleLang, SUPPORTED_LANGS, LANG_STORAGE_KEY });";
  return vm.runInNewContext(code, sandbox, { filename: "app.js" });
}

// 1. No URL param, no storage -> English.
assert.strictEqual(runApp("", null).lang, "en");

// 2. URL ?lang=zh-CN -> Chinese.
assert.strictEqual(runApp("?lang=zh-CN", null).lang, "zh-CN");

// 3. URL ?lang=en wins over stored zh-CN.
assert.strictEqual(runApp("?lang=en", "zh-CN").lang, "en");

// 4. URL ?lang=zh-CN wins over stored en.
assert.strictEqual(runApp("?lang=zh-CN", "en").lang, "zh-CN");

// 5. No URL param -> use localStorage.
assert.strictEqual(runApp("", "zh-CN").lang, "zh-CN");

// 6. Invalid lang falls back to English.
assert.strictEqual(runApp("?lang=invalid", null).lang, "en");

// 7. t() returns Chinese translations.
let r = runApp("?lang=zh-CN", null);
assert.strictEqual(r.t("daily.generate"), "生成报告");
assert.strictEqual(r.t("daily.eyebrow"), "每日报告");
assert.strictEqual(r.t("cat.news"), "新闻");
assert.strictEqual(r.t("status.connected"), "已连接");

// 8. t() returns English by default.
r = runApp("", null);
assert.strictEqual(r.t("daily.generate"), "Generate reports");

// 9. t() interpolates parameters.
r = runApp("", null);
assert.strictEqual(r.t("manage.added", { ticker: "AAPL" }), "AAPL added.");
r = runApp("?lang=zh-CN", null);
assert.strictEqual(r.t("manage.added", { ticker: "AAPL" }), "AAPL 已添加。");

// 10. Missing key falls back to the key itself (never undefined/null).
r = runApp("?lang=zh-CN", null);
assert.strictEqual(r.t("nonexistent.key"), "nonexistent.key");

console.log("i18n tests passed");
