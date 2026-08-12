"""Negative / honesty probes for Value Investors Club public surface.

Run manually (network): ``python tests/fixtures/vic/probe_public.py``

Uses stdlib urllib only — no cookie, no login. Captures evidence for
``SPIKE.md`` (2026-08-11).
"""

from __future__ import annotations

import hashlib
import re
from typing import List, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (compatible; InvestmentMonitor/0.1; +https://example.local)"
BASE = "https://valueinvestorsclub.com"


def fetch(path: str) -> Tuple[int, str, str]:
    url = path if path.startswith("http") else BASE + path
    req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
            content_type = response.headers.get("Content-Type", "")
            return int(response.status), content_type, body
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        return int(exc.code), "", body
    except URLError as exc:
        return 0, "", f"URLError: {exc}"


def idea_hrefs(body: str) -> List[str]:
    return re.findall(r'href=["\'](/idea/[^"\']+)["\']', body, flags=re.I)


def main() -> None:
    paths = [
        "/",
        "/ideas",
        "/ideas?symbol=MSFT",
        "/ideas?symbol=AAPL",
        "/ideas?q=MSFT",
        "/ideas/MSFT",
        "/search?q=MSFT",
        "/symbol/MSFT",
        "/feed",
        "/rss",
        "/api/ideas",
        "/api/v1/ideas",
        "/sitemap.xml",
        "/robots.txt",
        "/login",
        "/ideas/atoz",
        "/idea/MICROSOFT_CORP/8319612353",
    ]
    hashes = {}
    for path in paths:
        status, content_type, body = fetch(path)
        hrefs = idea_hrefs(body)
        digest = hashlib.md5(repr(tuple(hrefs)).encode()).hexdigest()[:8]
        has_rss = "<item" in body.lower() or "<entry" in body.lower()
        print(
            f"{path:40} HTTP {status:3} len={len(body):7} "
            f"ct={content_type[:28]!r:30} ideas={len(hrefs):4} "
            f"rss={has_rss} href_hash={digest}"
        )
        if path in ("/ideas", "/ideas?symbol=MSFT", "/ideas?symbol=AAPL"):
            hashes[path] = digest
        if "45" in body.lower() and "day" in body.lower():
            match = re.search(r".{0,40}45.{0,80}day.{0,80}", body, re.I)
            if match:
                print("  45-day note:", re.sub(r"\s+", " ", match.group(0))[:160])
    if hashes:
        print(
            "symbol filter equal?",
            hashes.get("/ideas")
            == hashes.get("/ideas?symbol=MSFT")
            == hashes.get("/ideas?symbol=AAPL"),
        )


if __name__ == "__main__":
    main()
