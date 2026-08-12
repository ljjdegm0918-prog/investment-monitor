"""X 官方 API v2 无 key 探测（stdlib urllib 仅限，Chrome UA，无 cookie）。

探测官方 X API v2（https://api.x.com/2/...）在**没有**任何凭据（无 Bearer
token、无 API key、无 cookie）时的行为：
  - GET /2/tweets/search/recent        — search recent posts（需要 query）
  - GET /2/users/by/username/{user}    — username -> user id 解析
  - GET /2/users/{id}/tweets           — user timeline（user tweets）
  - GET /2/news/search                 — news search（附送检查）

对每个 URL 分别用三种头探测：
  A) 无 Authorization 头（裸请求）
  B) Authorization: Bearer <假 token>（占位，非真实 key）
  C) 浏览器式 UA 无头（对照，确认非 UA/WAF 导致）

输出 Markdown 表格：URL | 变体 | HTTP | Content-Type | body 摘要
用法: python probe_api.py
"""
import io
import json
import sys
import urllib.error
import urllib.request

# 强制 stdout 使用 utf-8（Windows GBK 环境）
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 注意：只允许占位假 token，绝不写入真实凭据
FAKE_BEARER = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# 探测目标：(名称, URL)
TARGETS = [
    ("search recent (cashtag 查询)", "https://api.x.com/2/tweets/search/recent?query=%24NVDA&max_results=10"),
    ("search recent (ticker+日期)", "https://api.x.com/2/tweets/search/recent?query=%24NVDA%20lang%3Aen&max_results=10"),
    ("user lookup by username", "https://api.x.com/2/users/by/username/XDevelopers"),
    ("user tweets (timeline)", "https://api.x.com/2/users/2244994945/tweets?max_results=5"),
    ("news search", "https://api.x.com/2/news/search?keywords=AAPL&max_results=5"),
]

VARIANTS = [
    ("裸请求(无 Authorization)", {}),
    ("假 Bearer token", {"Authorization": "Bearer " + FAKE_BEARER}),
    ("浏览器 UA + 假 Bearer", {"Authorization": "Bearer " + FAKE_BEARER, "User-Agent": UA}),
]


def fetch(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            body = raw.decode("utf-8", errors="replace")
            return resp.status, resp.headers.get("Content-Type", ""), body
    except urllib.error.HTTPError as e:
        raw = e.read()
        body = raw.decode("utf-8", errors="replace")
        return e.code, e.headers.get("Content-Type", ""), body
    except urllib.error.URLError as e:
        return "ERR", "", "URLError: %s" % (e.reason,)


def summarize(body):
    """取 JSON body 前 200 字符作为摘要（截断 errors/meta）。"""
    b = body.strip()
    if not b:
        return "(empty body)"
    if len(b) > 220:
        b = b[:220] + " ..."
    return b.replace("\n", " ")


def main():
    print("## X API v2 no-key probes (%s)" % __import__("datetime").date.today().isoformat())
    print()
    print("| Probe | Variant | HTTP | Content-Type | body snippet |")
    print("|---|---|---|---|---|")
    for name, url in TARGETS:
        for vname, extra in VARIANTS:
            headers = {
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "close",
            }
            headers.update(extra)
            status, ctype, body = fetch(url, headers)
            print("| `%s` | %s | **%s** | %s | `%s` |" % (
                name, vname, status, ctype or "-", summarize(body)))
    print()
    print("注：URL 中 %24 = $（cashtag）。假 Bearer 为占位符，非真实 token。")


if __name__ == "__main__":
    main()
