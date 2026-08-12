"""Yellowbrick RSS/JSON feed 探针（stdlib urllib 仅限，浏览器 UA，无 cookie）。

探测 public RSS feed 和 WP REST API 端点。
输出 Markdown 表格行: URL | HTTP | id/time/title/link? | 摘要
用法: python probe_rss.py
"""
import io
import gzip
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

# 强制 stdout 使用 utf-8（Windows GBK 环境）
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

RSS_PROBES = [
    "https://yellowbrick.com/feed",
    "https://yellowbrick.com/rss",
    "https://yellowbrickresearch.com/feed",
    "https://yellowbrickresearch.com/rss",
    "https://ybrick.co/feed",
    "https://ybrick.co/rss",
    "https://joinyellowbrick.com/feed",
    "https://joinyellowbrick.com/rss",
    "https://yellowbrickinvesting.substack.com/feed",
]

JSON_PROBES = [
    "https://yellowbrick.com/wp-json/wp/v2/posts?per_page=2",
    "https://yellowbrick.com/wp-json/wp/v2/posts?per_page=2&_fields=id,date,title,link,slug,categories",
    "https://yellowbrick.com/wp-json/wp/v2/posts?per_page=2&categories=7",
    "https://yellowbrick.com/wp-json/wp/v2/posts?per_page=2&search=Netezza",
    "https://yellowbrick.com/wp-json/wp/v2/categories?per_page=20&_fields=id,name,slug,count",
    "https://yellowbrick.com/feed/json",
    "https://yellowbrick.com/wp-json",
]


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    })
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


def parse_rss_items(xml_text):
    """解析 RSS XML，提取 item 字段。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    ns = {
        'content': 'http://purl.org/rss/1.0/modules/content/',
        'dc': 'http://purl.org/dc/elements/1.1/',
    }
    channel = root.find('channel')
    if channel is None:
        return None
    items = channel.findall('item')
    results = []
    for it in items[:3]:
        guid = it.find('guid')
        results.append({
            'guid': guid.text if guid is not None else None,
            'isPermaLink': guid.get('isPermaLink') if guid is not None else None,
            'title': it.findtext('title', ''),
            'link': it.findtext('link', ''),
            'pubDate': it.findtext('pubDate', ''),
            'creator': it.findtext('dc:creator', '', ns),
            'category': it.findtext('category', ''),
        })
    return results


def parse_json_items(text):
    """解析 JSON 响应，提取前 2 条记录的关键字段。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        # WP REST discovery root
        return {'type': 'wp_root', 'namespaces': data.get('namespaces', [])[:5]}
    if not isinstance(data, list):
        return None
    results = []
    for p in data[:2]:
        results.append({
            'id': p.get('id'),
            'date': p.get('date'),
            'date_gmt': p.get('date_gmt'),
            'slug': p.get('slug'),
            'link': p.get('link'),
            'title': p.get('title', {}).get('rendered', ''),
            'categories': p.get('categories', []),
        })
    return results


def main():
    print("# Yellowbrick RSS/JSON Feed 探针（stdlib urllib, Chrome UA, 无 cookie）")
    print()

    # --- RSS probes ---
    print("## RSS Feeds")
    print()
    print("| URL | HTTP | id | time | title | link | 摘要 |")
    print("|---|---|---|---|---|---|---|")
    for url in RSS_PROBES:
        status, body, ct = fetch(url)
        if status == 200 and '<?xml' in body[:200]:
            items = parse_rss_items(body)
            if items:
                for i, it in enumerate(items[:2]):
                    prefix = f"item{i+1}" if len(items) > 1 else "item"
                    title_safe = it['title'][:50].encode('ascii', 'replace').decode()
                    link_safe = it['link'][:60].encode('ascii', 'replace').decode()
                    print(f"| `{url}` | {status} | `{it['guid'][:40]}` | `{it['pubDate']}` | {title_safe}... | {link_safe}... | RSS OK, category={it['category']} |")
            else:
                print(f"| `{url}` | {status} | — | — | — | — | XML parse fail |")
        elif status == 200:
            head = body[:120].replace('\n', ' ')
            print(f"| `{url}` | {status} | — | — | — | — | non-RSS content: {head!r} |")
        else:
            print(f"| `{url}` | {status} | — | — | — | — | error |")

    # --- JSON probes ---
    print()
    print("## JSON / WP REST API")
    print()
    print("| URL | HTTP | 摘要 |")
    print("|---|---|---|")
    for url in JSON_PROBES:
        status, body, ct = fetch(url)
        if status == 200:
            items = parse_json_items(body)
            if items is None:
                head = body[:120].replace('\n', ' ')
                print(f"| `{url}` | {status} | non-JSON: {head!r} |")
            elif isinstance(items, dict) and items.get('type') == 'wp_root':
                print(f"| `{url}` | {status} | WP REST root, namespaces={items['namespaces']} |")
            else:
                for i, it in enumerate(items):
                    cats = it.get('categories', [])
                    print(f"| `{url}` | {status} | item{i+1}: id={it['id']} date={it['date']} title={it['title'][:50]}... cats={cats} |")
        else:
            print(f"| `{url}` | {status} | error |")

    # --- RSS field structure detail ---
    print()
    print("## RSS Item Field Structure (yellowbrick.com/feed)")
    print()
    status, body, _ = fetch("https://yellowbrick.com/feed")
    if status == 200:
        items = parse_rss_items(body)
        if items and items[0]:
            it = items[0]
            print("| Field | Value |")
            print("|---|---|")
            print(f"| guid | `{it['guid']}` |")
            print(f"| guid.isPermaLink | `{it['isPermaLink']}` |")
            print(f"| title | {it['title'][:80]} |")
            print(f"| link | `{it['link']}` |")
            print(f"| pubDate | `{it['pubDate']}` |")
            print(f"| dc:creator | {it['creator']} |")
            print(f"| category | {it['category']} |")


if __name__ == "__main__":
    main()
