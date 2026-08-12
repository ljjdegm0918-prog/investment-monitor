"""Substack ticker/search 公开表面探测（stdlib urllib only, Chrome UA, 无 cookie）。

探测 Substack 是否支持按 US ticker / keyword 检索公共内容：
  - 全局搜索页 / 搜索 API
  - tag 页（ticker tag 是否存在）
  - topic / category 页
  - 发现页（archive / browse）
  - 出版物内搜索

输出 Markdown 表格行: URL | HTTP | login/paywall? | can filter by ticker? stable fields?
用法: python probe_ticker_search.py
"""
import io
import gzip
import json
import re
import sys
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

# 强制 stdout 使用 utf-8（Windows GBK 环境）
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 用于探测的 ticker + keyword
TICKERS = ["NVDA", "AAPL", "TSLA"]
KEYWORDS = ["NVIDIA", "Apple", "Tesla"]


def fetch(url, headers=None):
    hdrs = {
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    }
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            ct = resp.headers.get("Content-Type", "")
            return resp.status, raw.decode("utf-8", errors="replace"), ct
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        except Exception:
            pass
        return e.code, raw.decode("utf-8", errors="replace"), ""
    except Exception as e:
        return 0, f"EXC {type(e).__name__}: {e}", ""


def is_paywalled(text):
    low = text.lower()
    strong_hits = []
    for h in ["paywall", "paid subscribers", "free trial", "membership"]:
        if h in low:
            strong_hits.append(h)
    return bool(strong_hits), strong_hits


def first_json_object(text):
    """从 HTML 里找第一个 JSON 响应或 <script type="application/ld+json">。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    return None


def extract_links_with_text(html, pattern):
    """提取含特定文本的链接。"""
    results = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href, text = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if pattern.lower() in text.lower() or pattern.lower() in href.lower():
            results.append((href, text[:60]))
    return results[:5]


def probe_search_page():
    """探测 Substack 全局搜索页。"""
    print("## 1. Substack 全局搜索页")
    print()
    print("| URL | HTTP | login/paywall? | can filter by ticker? stable fields? |")
    print("|---|---|---|---|")

    # 搜索页主页
    for ticker in TICKERS[:1]:  # NVDA 作为代表
        encoded = urllib.parse.quote(ticker)
        url = f"https://substack.com/search?q={encoded}"
        status, body, ct = fetch(url)
        paywall, hints = is_paywalled(body)
        # 检查是否含搜索结果
        has_results = "result" in body.lower() or "post" in body.lower()
        # 提取 title
        title_m = re.search(r'<title>(.*?)</title>', body, re.S)
        title = title_m.group(1).strip() if title_m else "—"
        print(f"| `GET {url}` | {status} | {'YES ' + str(hints) if paywall else 'no paywall hint'} | "
              f"search page, title={title[:50]!r}, body_len={len(body)}, has_results_hint={has_results} |")
    print()


def probe_search_api():
    """探测 Substack 搜索 API。"""
    print("## 2. Substack 搜索 API")
    print()
    print("| URL | HTTP | login/paywall? | can filter by ticker? stable fields? |")
    print("|---|---|---|---|")

    for ticker in TICKERS:
        encoded = urllib.parse.quote(ticker)
        # 常见搜索 API 模式
        apis = [
            f"https://substack.com/api/v1/search?q={encoded}&limit=5",
            f"https://substack.com/api/v2/search?q={encoded}&limit=5",
            f"https://substack.com/api/search?q={encoded}&limit=5",
        ]
        for api_url in apis:
            status, body, ct = fetch(api_url)
            if status == 200:
                data = first_json_object(body)
                if isinstance(data, (list, dict)):
                    if isinstance(data, list):
                        print(f"| `GET {api_url}` | {status} | public JSON | "
                              f"list len={len(data)}, first_keys={list(data[0].keys())[:6] if data else 'empty'} |")
                    else:
                        print(f"| `GET {api_url}` | {status} | public JSON | "
                              f"dict keys={list(data.keys())[:8]} |")
                else:
                    head = body[:120].replace("\n", " ")
                    print(f"| `GET {api_url}` | {status} | non-JSON: {head!r} |")
            elif status != 0:
                print(f"| `GET {api_url}` | {status} | — | error |")
            else:
                print(f"| `GET {api_url}` | 0 (transport) | — | connection failed |")
    print()


def probe_tag_pages():
    """探测 Substack tag 页（ticker tag 是否存在）。"""
    print("## 3. Substack Tag 页")
    print()
    print("| URL | HTTP | login/paywall? | can filter by ticker? stable fields? |")
    print("|---|---|---|---|")

    for ticker in TICKERS:
        encoded = urllib.parse.quote(ticker.lower())
        url = f"https://substack.com/tag/{encoded}"
        status, body, ct = fetch(url)
        paywall, hints = is_paywalled(body)
        title_m = re.search(r'<title>(.*?)</title>', body, re.S)
        title = title_m.group(1).strip() if title_m else "—"
        # 检查是否是 404 / tag 不存在
        is_404 = status == 404 or "not found" in body.lower()[:500]
        print(f"| `GET {url}` | {status} | {'YES ' + str(hints) if paywall else 'no paywall hint'} | "
              f"title={title[:50]!r}, is_404_hint={is_404}, body_len={len(body)} |")
    print()


def probe_topic_category():
    """探测 Substack topic / category / discover 页。"""
    print("## 4. Substack Topic / Category / Discover 页")
    print()
    print("| URL | HTTP | login/paywall? | can filter by ticker? stable fields? |")
    print("|---|---|---|---|")

    urls = [
        "https://substack.com/discover",
        "https://substack.com/browse",
        "https://substack.com/topics",
        "https://substack.com/discover/finance",
        "https://substack.com/discover/investing",
        "https://substack.com/discover/stocks",
    ]
    for url in urls:
        status, body, ct = fetch(url)
        paywall, hints = is_paywalled(body)
        title_m = re.search(r'<title>(.*?)</title>', body, re.S)
        title = title_m.group(1).strip() if title_m else "—"
        print(f"| `GET {url}` | {status} | {'YES ' + str(hints) if paywall else 'no paywall hint'} | "
              f"title={title[:50]!r}, body_len={len(body)} |")
    print()


def probe_publication_search():
    """探测出版物内搜索（特定 publication 的搜索/tag 页）。"""
    print("## 5. 出版物内搜索 / Tag 页")
    print()
    print("| URL | HTTP | login/paywall? | can filter by ticker? stable fields? |")
    print("|---|---|---|---|")

    pub = "noahpinion.substack.com"
    for ticker in TICKERS:
        encoded = urllib.parse.quote(ticker)
        # 出版物内搜索
        url = f"https://{pub}/search?q={encoded}"
        status, body, ct = fetch(url)
        paywall, hints = is_paywalled(body)
        title_m = re.search(r'<title>(.*?)</title>', body, re.S)
        title = title_m.group(1).strip() if title_m else "—"
        print(f"| `GET {url}` | {status} | {'YES ' + str(hints) if paywall else 'no paywall hint'} | "
              f"title={title[:50]!r}, body_len={len(body)} |")

    # 出版物内 tag 页
    for ticker in TICKERS:
        encoded = urllib.parse.quote(ticker.lower())
        url = f"https://{pub}/tag/{encoded}"
        status, body, ct = fetch(url)
        paywall, hints = is_paywalled(body)
        title_m = re.search(r'<title>(.*?)</title>', body, re.S)
        title = title_m.group(1).strip() if title_m else "—"
        print(f"| `GET {url}` | {status} | {'YES ' + str(hints) if paywall else 'no paywall hint'} | "
              f"title={title[:50]!r}, body_len={len(body)} |")
    print()


def probe_archive_date():
    """探测按日期过滤能力（archive 页是否支持日期导航）。"""
    print("## 6. 按日期过滤能力（archive 日期导航）")
    print()
    print("| URL | HTTP | login/paywall? | can filter by ticker? stable fields? |")
    print("|---|---|---|---|")

    pub = "noahpinion.substack.com"
    # archive 页通常按 YYYY/MM/DD 组织
    urls = [
        f"https://{pub}/archive",
        f"https://{pub}/archive/2026/08/11",
        f"https://{pub}/archive/2026-08-11",
        f"https://{pub}/api/v1/archive?sort=new&limit=5&start=2026-08-11",
        f"https://{pub}/api/v1/archive?sort=new&limit=5&year=2026&month=8",
    ]
    for url in urls:
        status, body, ct = fetch(url)
        paywall, hints = is_paywalled(body)
        data = first_json_object(body) if status == 200 else None
        if isinstance(data, list) and data:
            print(f"| `GET {url}` | {status} | no login | "
                  f"list len={len(data)}, sample_id={data[0].get('id')}, date={str(data[0].get('post_date'))[:19]} |")
        elif isinstance(data, dict):
            print(f"| `GET {url}` | {status} | no login | dict keys={list(data.keys())[:6]} |")
        else:
            title_m = re.search(r'<title>(.*?)</title>', body, re.S)
            title = title_m.group(1).strip() if title_m else "—"
            print(f"| `GET {url}` | {status} | {'YES ' + str(hints) if paywall else 'no paywall hint'} | "
                  f"title={title[:50]!r}, body_len={len(body)} |")
    print()


def main():
    print("# Substack ticker/search 公开表面探测（stdlib urllib, Chrome UA, 无 cookie）")
    print()
    print(f"探测日 2026-08-11。Ticker: {TICKERS}。Keyword: {KEYWORDS}。")
    print()
    probe_search_page()
    probe_search_api()
    probe_tag_pages()
    probe_topic_category()
    probe_publication_search()
    probe_archive_date()


if __name__ == "__main__":
    main()
