"""Seeking Alpha symbol 页面探针（stdlib urllib 仅限，浏览器 UA，无 cookie）。

只做只读 GET 探测，不绕过登录/验证码/WAF。输出 Markdown 表格行，
列: URL | HTTP | login? | id/time/title/link?
用法: python probe_symbol.py
"""
import gzip
import io
import re
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

PROBES = [
    # AAPL symbol 页面（HTML）
    "https://seekingalpha.com/symbol/AAPL",
    "https://seekingalpha.com/symbol/AAPL/forum",
    "https://seekingalpha.com/symbol/AAPL/comments",
    "https://seekingalpha.com/symbol/AAPL/news",
    "https://seekingalpha.com/symbol/AAPL/analysis",
    "https://seekingalpha.com/symbol/AAPL/transcripts",
    "https://seekingalpha.com/symbol/AAPL/earnings",
    "https://seekingalpha.com/symbol/AAPL/dividends",
    # 可能的公开 API / RSS 变体
    "https://seekingalpha.com/api/sa/combined/AAPL.xml",
    "https://seekingalpha.com/api/sa/combined/AAPL",
    "https://seekingalpha.com/symbol/AAPL/rss",
]

# 登录墙关键词（小写匹配）
LOGIN_TOKENS = [
    "log in", "login", "sign in", "sign up", "signup", "subscribe",
    "unlock", "become a member", "create a free account", "join seeking alpha",
]
# 帖子/文章结构化字段（id / time / title / link）迹象
ID_TIME_TITLE_LINK_PATTERNS = [
    ("article link", r'href="[^"]*/article/[^"]*"'),
    ("comment link", r'href="[^"]*/comment/[^"]*"'),
    ("datetime attr", r'datetime="[^"]+"'),
    ("datePublished", r'datePublished'),
    ("data-sa-entity-id", r'data-sa-entity-id'),
    ("json post id", r'"id"\s*:\s*\d{5,}'),
    ("item prop date", r'itemprop="datePublished"'),
    ("time tag", r'<time[^>]*>'),
    # XML RSS 结构
    ("rss item", r'<item>'),
    ("rss pubDate", r'<pubDate>'),
    ("rss guid", r'<guid[^>]*>'),
    ("rss title", r'<title>'),
    ("rss link", r'<link>'),
]


def fetch(url: str) -> tuple[int, str, list[str]]:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            status = resp.status
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            return status, raw.decode("utf-8", errors="replace"), list(resp.headers.get_all("Set-Cookie") or [])
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        except Exception:
            pass
        return e.code, raw.decode("utf-8", errors="replace"), list(e.headers.get_all("Set-Cookie") or [])
    except Exception as e:  # noqa: BLE001
        return 0, f"EXC {type(e).__name__}: {e}", []


def login_flag(text: str) -> str:
    low = text.lower()
    hits = [t for t in LOGIN_TOKENS if t in low]
    return "Y" if hits else "N"


def struct_flag(text: str) -> str:
    """返回在响应中找到的结构化字段标记，如 'article-link+datetime' 或 'none'。"""
    found = []
    for label, pat in ID_TIME_TITLE_LINK_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            found.append(label)
    return "+".join(found) if found else "none"


def main() -> None:
    print("# Seeking Alpha symbol 页面探针（NO cookie, stdlib urllib, Chrome UA）")
    print()
    print("| URL | HTTP | login? | id/time/title/link? |")
    print("|---|---|---|---|")
    for url in PROBES:
        status, body, sc = fetch(url)
        note = f"Set-Cookie={len(sc)}; len={len(body)}"
        login = login_flag(body)
        struct = struct_flag(body)
        print(f"| `{url}` | {status} | {login} | {struct} ({note}) |")


if __name__ == "__main__":
    main()
