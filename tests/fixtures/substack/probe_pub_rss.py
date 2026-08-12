"""Substack 公共出版物探测（stdlib urllib 仅限，Chrome UA，无 cookie）。

探测 Substack 公共 newsletter 的表面（非 waitlist）：
  - publication home (HTML)
  - /feed (RSS 2.0)
  - 公共 JSON API (/api/v1/archive, /api/v1/posts)

输出 Markdown 表格行: URL | HTTP | login/paywall? | stable id/time/title/link?
用法: python probe_pub_rss.py
"""
import io
import gzip
import json
import re
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

# 强制 stdout 使用 utf-8（Windows GBK 环境）
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 2-3 个真实公共 Substack 出版物（非 waitlist、非 yellowbrick）
PUBLICATIONS = [
    "noahpinion.substack.com",
    "thediff.substack.com",
    "notboring.substack.com",
]

# 付费/登录墙关键词（用于 HTML 与 RSS 摘要启发式判断）
PAYWALL_HINTS = [
    "paywall", "subscribe to", "free trial", "paid subscribers",
    "membership", "sign in", "sign up", "login",
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


def is_paywalled(text):
    low = text.lower()
    hits = [h for h in PAYWALL_HINTS if h in low]
    # "subscribe" 几乎每个 substack 都有；只在同时出现付费词时才判为 paywall
    strong = [h for h in hits if h not in ("subscribe to", "sign in", "sign up", "login")]
    return (bool(strong), hits[:4])


def parse_rss_items(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    channel = root.find("channel")
    if channel is None:
        return None
    ns = {"dc": "http://purl.org/dc/elements/1.1/"}
    results = []
    for it in channel.findall("item")[:2]:
        guid = it.find("guid")
        results.append({
            "guid": guid.text if guid is not None else None,
            "isPermaLink": guid.get("isPermaLink") if guid is not None else None,
            "title": it.findtext("title", ""),
            "link": it.findtext("link", ""),
            "pubDate": it.findtext("pubDate", ""),
            "creator": it.findtext("dc:creator", "", ns),
        })
    return results


def first_json_object(text):
    """在 HTML 里找第一个 <script type="application/ld+json"> 或纯 JSON 响应。"""
    text = text.strip()
    try:
        data = json.loads(text)
        return data
    except json.JSONDecodeError:
        pass
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    return None


def probe_publication(pub):
    base = f"https://{pub}"
    print(f"## {pub}")
    print()

    # --- home ---
    status, body, ct = fetch(f"{base}/")
    paywall, hints = is_paywalled(body)
    ld = first_json_object(body)
    ld_note = ""
    if isinstance(ld, list) and ld:
        first = ld[0]
        ld_note = (f"JSON-LD {first.get('@type')} name={first.get('name','')[:30]!r} "
                   f"headline={str(first.get('headline',''))[:30]!r}")
    elif isinstance(ld, dict):
        ld_note = (f"JSON-LD {ld.get('@type')} name={str(ld.get('name',''))[:30]!r} "
                   f"headline={str(ld.get('headline',''))[:30]!r}")
    print("| Probe | HTTP | login/paywall? | stable id/time/title/link? |")
    print("|---|---|---|---|")
    print(f"| `GET {base}/` | {status} | "
          f"{'YES ' + str(hints) if paywall else 'no paywall hint'} | "
          f"{ld_note or 'no JSON-LD in first bytes'} |")

    # --- feed ---
    status, body, ct = fetch(f"{base}/feed")
    if status == 200 and "<?xml" in body[:200]:
        items = parse_rss_items(body)
        if items:
            for i, it in enumerate(items):
                print(f"| `GET {base}/feed` | {status} | no login needed (public RSS) | "
                      f"guid={it['guid'][:44]!r} pubDate={it['pubDate']!r} "
                      f"title={it['title'][:30]!r} link={it['link'][:50]!r} |")
        else:
            print(f"| `GET {base}/feed` | {status} | no login needed | XML parse fail |")
    elif status == 200:
        head = body[:100].replace("\n", " ")
        print(f"| `GET {base}/feed` | {status} | no login needed | non-RSS content: {head!r} |")
    else:
        print(f"| `GET {base}/feed` | {status} | — | error |")

    # --- public JSON API ---
    for api in [f"/api/v1/archive?sort=new&limit=2",
                f"/api/v1/posts?limit=2",
                f"/api/v1/publication"]:
        status, body, ct = fetch(base + api)
        if status == 200:
            data = first_json_object(body)
            if isinstance(data, list) and data:
                p = data[0]
                print(f"| `GET {base}{api}` | {status} | public JSON | "
                      f"id={p.get('id')} post_date={str(p.get('post_date'))[:19]} "
                      f"title={str(p.get('title'))[:30]!r} "
                      f"canonical_url={str(p.get('canonical_url'))[:50]!r} |")
            elif isinstance(data, dict):
                keys = list(data.keys())[:6]
                print(f"| `GET {base}{api}` | {status} | public JSON | "
                      f"dict keys={keys} |")
            else:
                head = body[:100].replace("\n", " ")
                print(f"| `GET {base}{api}` | {status} | non-JSON: {head!r} |")
        else:
            print(f"| `GET {base}{api}` | {status} | — | error |")
    print()


def main():
    print("# Substack 公共出版物探测（stdlib urllib, Chrome UA, 无 cookie）")
    print()
    print("出版物选择：3 个真实公共 Substack newsletter（非 waitlist、非 yellowbrick）")
    print()
    for pub in PUBLICATIONS:
        probe_publication(pub)


if __name__ == "__main__":
    main()
