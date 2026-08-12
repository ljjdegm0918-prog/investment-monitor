"""Xueqiu 公开讨论面探针（stdlib urllib 仅限，浏览器 UA，无 cookie）。

只做只读 GET 探测，不绕过登录/验证码。输出 Markdown 表格行。
用法: python probe.py [--cookie XUEQIU_COOKIE 值]  # cookie 路径为可选对照，默认不带
"""
import gzip
import io
import json
import sys
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

PROBES = [
    # 股票讨论页面（HTML）
    "https://xueqiu.com/S/SH600519",
    "https://xueqiu.com/S/SZ000001",
    "https://xueqiu.com/S/HK00700",
    # 历史/公开 API 变体（已知均要求 xq_a_token）
    "https://xueqiu.com/statuses/search.json?symbol=SH600519&count=10",
    "https://xueqiu.com/query/v1/symbol/search/status.json?symbol=SH600519&count=10",
    "https://xueqiu.com/query/v1/symbol/search/status.json?symbol=SZ000001&count=10",
    "https://xueqiu.com/query/v1/symbol/search/status.json?symbol=HK00700&count=10",
    "https://stock.xueqiu.com/v5/stock/quote.json?symbol=SH600519",
    # 热帖/时间线
    "https://xueqiu.com/statuses/hot/listV2.json?since_id=-1&max_id=-1&size=10",
    "https://xueqiu.com/statuses/original/timeline.json?count=10",
]


def fetch(url: str, cookie: str | None) -> tuple[int, str, list[str]]:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "close",
    })
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.status
            raw = resp.read()
            # 解 gzip（部分接口返回 gzip）
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            set_cookie = resp.headers.get_all("Set-Cookie") or []
            return status, raw.decode("utf-8", errors="replace"), list(set_cookie)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        except Exception:
            pass
        return e.code, raw.decode("utf-8", errors="replace"), list(e.headers.get_all("Set-Cookie") or [])
    except Exception as e:  # noqa: BLE001
        return 0, f"EXC {type(e).__name__}: {e}", []


def summarize(text: str) -> str:
    t = text.strip()
    if not t:
        return "empty"
    # 若为 JSON，压缩显示关键字段
    if t.startswith("{"):
        try:
            j = json.loads(t)
            keys = list(j.keys())[:8]
            return f"JSON keys={keys} len={len(t)}"
        except Exception:
            pass
    return f"text len={len(t)} head={t[:120]!r}"


def main() -> None:
    cookie = None
    if "--cookie" in sys.argv:
        i = sys.argv.index("--cookie")
        cookie = sys.argv[i + 1]
    mode = "WITH cookie" if cookie else "NO cookie"
    print(f"# Xueqiu probe ({mode}, {UA[:40]}...)")
    print()
    print("| URL | HTTP | Set-Cookie? | 响应摘要 |")
    print("|---|---|---|---|")
    for url in PROBES:
        status, body, sc = fetch(url, cookie)
        note = summarize(body)
        print(f"| `{url}` | {status} | {len(sc)} | {note} |")


if __name__ == "__main__":
    main()
