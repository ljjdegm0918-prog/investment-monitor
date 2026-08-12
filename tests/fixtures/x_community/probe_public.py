"""X / Twitter 公共表面探测（stdlib urllib 仅限，Chrome UA，无 cookie）。

探测 X (Twitter) 公共 syndication / embed / HTML 表面，验证在无 API key
（无 Bearer token）情况下能否稳定采集公开内容。

输出 Markdown 表格行: URL | HTTP | login/bot-wall? | usable content?
用法: python probe_public.py
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

# 金融/市场相关公开账号（非私密、非受保护）
FINANCE_USERS = [
    "NYSE",          # 纽约证券交易所
    "WSJ",           # 华尔街日报
    "business",      # Bloomberg
    "Stocktwits",    # Stocktwits
]

# 一个真实存在的公开 tweet id（Elon Musk 2022-10-27 收购推特相关，id ~1585174128448）
SAMPLE_TWEET_ID = "1585174128448"
SAMPLE_TWEET_URL = f"https://x.com/Twitter/status/{SAMPLE_TWEET_ID}"

# Nitter 公开实例（社区维护，随时可能下线）
NITTER_INSTANCES = [
    "nitter.net",
    "nitter.privacydev.net",
    "nitter.poast.org",
    "nitter.1d4.us",
]


def fetch(url, accept="*/*"):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": accept,
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


def head_snippet(text, n=120):
    text = text.replace("\n", " ").replace("\r", " ").strip()
    return text[:n]


def has_bot_wall(text):
    """启发式判断 X/Twitter 是否返回 bot wall / 空壳 SPA。"""
    low = text.lower()
    signals = {
        "something went wrong": "SPA error shell (client-rendered, no SSR)",
        "javascript is not available": "bot wall: JS required",
        "this browser is not supported": "bot wall: browser check",
        "real people, real voices": "empty X landing shell",
        "don't miss what's happening": "empty X landing shell",
        "guest_id": "set-cookie guest_id (tracking, not content)",
        "gt=": "guest token in body (tracking, not content)",
    }
    for sig, note in signals.items():
        if sig in low:
            return note
    return None


def parse_rss_items(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    channel = root.find("channel")
    if channel is None:
        return None
    results = []
    for it in channel.findall("item")[:3]:
        results.append({
            "guid": it.findtext("guid", ""),
            "title": it.findtext("title", ""),
            "link": it.findtext("link", ""),
            "pubDate": it.findtext("pubDate", ""),
            "description": head_snippet(it.findtext("description", ""), 80),
        })
    return results


# ─── 探测 1: 直接 X.com HTML ──────────────────────────────────────

def probe_direct_html():
    print("## 1. 直接 x.com / twitter.com HTML（预期 bot wall）")
    print()
    print("| Probe | HTTP | login/bot-wall? | usable content? |")
    print("|---|---|---|---|")

    # x.com home
    status, body, ct = fetch("https://x.com/")
    wall = has_bot_wall(body)
    print(f"| `GET https://x.com/` | {status} | {wall or 'no obvious wall'} | "
          f"{'no (empty shell)' if wall else head_snippet(body)} |")

    # x.com user timeline
    for user in ["NYSE", "WSJ"]:
        status, body, ct = fetch(f"https://x.com/{user}")
        wall = has_bot_wall(body)
        # 检查是否有 tweet 内容（SSR 渲染的 tweet 文本）
        has_tweets = bool(re.search(r'data-testid="tweet"', body))
        print(f"| `GET https://x.com/{user}` | {status} | "
              f"{wall or 'no obvious wall'} | "
              f"{'no (bot wall / empty shell)' if wall else f'tweet SSR={has_tweets} snippet={head_snippet(body)}'} |")

    # x.com ticker search
    status, body, ct = fetch("https://x.com/search?q=NVDA&f=live")
    wall = has_bot_wall(body)
    has_tweets = bool(re.search(r'data-testid="tweet"', body))
    print(f"| `GET https://x.com/search?q=NVDA&f=live` | {status} | "
          f"{wall or 'no obvious wall'} | "
          f"{'no (bot wall)' if wall else f'tweet SSR={has_tweets}'} |")

    # twitter.com redirect
    status, body, ct = fetch("https://twitter.com/")
    print(f"| `GET https://twitter.com/` | {status} | redirect to x.com | "
          f"snippet={head_snippet(body)} |")

    print()


# ─── 探测 2: oEmbed (publish.twitter.com) ─────────────────────────

def probe_oembed():
    print("## 2. oEmbed 端点 (publish.twitter.com/oembed)")
    print()
    print("| Probe | HTTP | login? | usable content? |")
    print("|---|---|---|---|")

    # oEmbed with a real tweet URL
    url = f"https://publish.twitter.com/oembed?url={SAMPLE_TWEET_URL}&omit_script=true"
    status, body, ct = fetch(url)
    if status == 200:
        try:
            data = json.loads(body)
            html = data.get("html", "")[:100]
            author = data.get("author_name", "")
            print(f"| `GET publish.twitter.com/oembed?url=...` | {status} | no login | "
                  f"✅ author={author!r} html_snippet={html!r} |")
        except json.JSONDecodeError:
            print(f"| `GET publish.twitter.com/oembed?url=...` | {status} | no login | "
                  f"non-JSON: {head_snippet(body)} |")
    else:
        print(f"| `GET publish.twitter.com/oembed?url=...` | {status} | — | error: {head_snippet(body)} |")

    # oEmbed with a search URL (ticker)
    url = "https://publish.twitter.com/oembed?url=https://x.com/search?q=NVDA"
    status, body, ct = fetch(url)
    print(f"| `GET publish.twitter.com/oembed?url=...search?q=NVDA` | {status} | — | "
          f"{head_snippet(body)} |")

    print()


# ─── 探测 3: Syndication (cdn.syndication.twimg.com) ──────────────

def probe_syndication():
    print("## 3. Syndication 端点 (cdn.syndication.twimg.com)")
    print()
    print("| Probe | HTTP | login? | usable content? |")
    print("|---|---|---|---|")

    # tweet-result syndication (used by embed)
    url = f"https://cdn.syndication.twimg.com/tweet-result?id={SAMPLE_TWEET_ID}&token=x"
    status, body, ct = fetch(url)
    if status == 200:
        try:
            data = json.loads(body)
            text = data.get("text", "")[:100]
            print(f"| `GET cdn.syndication.twimg.com/tweet-result?id=...` | {status} | no login | "
                  f"✅ text_snippet={text!r} |")
        except json.JSONDecodeError:
            print(f"| `GET cdn.syndication.twimg.com/tweet-result?id=...` | {status} | no login | "
                  f"non-JSON: {head_snippet(body)} |")
    else:
        print(f"| `GET cdn.syndication.twimg.com/tweet-result?id=...` | {status} | — | "
              f"error: {head_snippet(body)} |")

    # tweet-result with lang
    url = f"https://cdn.syndication.twimg.com/tweet-result?id={SAMPLE_TWEET_ID}&lang=en&token=x"
    status, body, ct = fetch(url)
    print(f"| `GET cdn.syndication.twimg.com/tweet-result?id=...&lang=en` | {status} | — | "
          f"{head_snippet(body)} |")

    print()


# ─── 探测 4: publish.twitter.com embed 页 ─────────────────────────

def probe_publish_embed():
    print("## 4. publish.twitter.com 嵌入页")
    print()
    print("| Probe | HTTP | login? | usable content? |")
    print("|---|---|---|---|")

    url = f"https://publish.twitter.com/?query={SAMPLE_TWEET_URL}&widget=Tweet"
    status, body, ct = fetch(url)
    wall = has_bot_wall(body)
    has_tweet = bool(re.search(r'data-testid="tweet"', body)) or "tweet" in body.lower()[:500]
    print(f"| `GET publish.twitter.com/?query=...&widget=Tweet` | {status} | "
          f"{wall or 'no'} | tweet_content={has_tweet} snippet={head_snippet(body)} |")

    print()


# ─── 探测 5: Nitter RSS 镜像 ──────────────────────────────────────

def probe_nitter():
    print("## 5. Nitter RSS 镜像（社区实例，随时可能下线）")
    print()
    print("| Probe | HTTP | login? | usable content? |")
    print("|---|---|---|---|")

    for host in NITTER_INSTANCES:
        base = f"https://{host}"

        # 先探测实例是否存活
        status, body, ct = fetch(f"{base}/")
        alive = status == 200
        wall = has_bot_wall(body) if alive else None
        print(f"| `GET {base}/` (instance liveness) | {status} | "
              f"{wall or 'no'} | "
              f"{'alive' if alive else f'dead/error: {head_snippet(body, 80)}'} |")

        if not alive:
            continue

        # RSS feed for a finance user
        for user in ["NYSE", "business"]:
            url = f"{base}/{user}/rss"
            status, body, ct = fetch(url, accept="application/rss+xml,application/xml,text/xml,*/*")
            if status == 200 and "<?xml" in body[:200]:
                items = parse_rss_items(body)
                if items:
                    it = items[0]
                    print(f"| `GET {base}/{user}/rss` | {status} | no login | "
                          f"✅ RSS items found; first: title={it['title'][:40]!r} "
                          f"pubDate={it['pubDate']!r} link={it['link'][:50]!r} |")
                else:
                    print(f"| `GET {base}/{user}/rss` | {status} | no login | "
                          f"XML but no RSS items parsed |")
            elif status == 200:
                print(f"| `GET {base}/{user}/rss` | {status} | — | "
                      f"non-XML: {head_snippet(body)} |")
            else:
                print(f"| `GET {base}/{user}/rss` | {status} | — | "
                      f"error: {head_snippet(body)} |")

    print()


# ─── 探测 6: Nitter 前端 HTML ─────────────────────────────────────

def probe_nitter_html():
    print("## 6. Nitter 前端 HTML（无 JS 渲染）")
    print()
    print("| Probe | HTTP | login? | usable content? |")
    print("|---|---|---|---|")

    for host in NITTER_INSTANCES[:2]:  # 只测前两个存活的
        base = f"https://{host}"
        # 先确认存活
        s, _, _ = fetch(f"{base}/")
        if s != 200:
            continue

        for user in ["NYSE"]:
            url = f"{base}/{user}"
            status, body, ct = fetch(url)
            if status == 200:
                # 检查是否有 tweet 内容
                has_tweet = bool(re.search(r'class="tweet-content', body))
                has_timeline = bool(re.search(r'class="timeline', body))
                print(f"| `GET {base}/{user}` | {status} | no login | "
                      f"tweet_content={has_tweet} timeline={has_timeline} "
                      f"snippet={head_snippet(body)} |")
            else:
                print(f"| `GET {base}/{user}` | {status} | — | error |")

    print()


# ─── 探测 7: 其他已知 syndication 路径 ────────────────────────────

def probe_other_syndication():
    print("## 7. 其他已知 syndication / 遗留路径")
    print()
    print("| Probe | HTTP | login? | usable content? |")
    print("|---|---|---|---|")

    # video syndication
    url = f"https://video.twimg.com/ext_tw_video/{SAMPLE_TWEET_ID}/pu/vid/1280x720/test.mp4"
    status, body, ct = fetch(url)
    print(f"| `GET video.twimg.com/...` (video) | {status} | — | content-type={ct} |")

    # 旧 syndication timeline (deprecated)
    url = "https://syndication.twitter.com/timeline/profile?screen_name=Twitter"
    status, body, ct = fetch(url)
    print(f"| `GET syndication.twitter.com/timeline/profile` (legacy) | {status} | — | "
          f"{head_snippet(body)} |")

    # 旧 syndication favorites
    url = "https://syndication.twitter.com/timeline/favorites?screen_name=Twitter"
    status, body, ct = fetch(url)
    print(f"| `GET syndication.twitter.com/timeline/favorites` (legacy) | {status} | — | "
          f"{head_snippet(body)} |")

    print()


def main():
    print("# X / Twitter 公共表面探测（stdlib urllib, Chrome UA, 无 cookie）")
    print()
    print(f"探测日 2026-08-11。样本 tweet id: `{SAMPLE_TWEET_ID}`")
    print()
    print("约束：urllib only，无 Selenium/Playwright，无 Bearer token / API key，无 cookie。")
    print()

    probe_direct_html()
    probe_oembed()
    probe_syndication()
    probe_publish_embed()
    probe_nitter()
    probe_nitter_html()
    probe_other_syndication()


if __name__ == "__main__":
    main()
