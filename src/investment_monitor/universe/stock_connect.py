# -*- coding: utf-8 -*-
"""CN <-> HK Stock Connect venue mapping (P5-1, static reference).

Plan §3.4: China equities are exposed through Hong Kong Stock Connect;
this module records that relationship only. It deliberately does **not**
open a CN regulatory disclosure connector — issuer disclosure for a CN
company stays with its home market / HK venue, and the repo's ``cn``
market remains an ``extra`` catalog entry.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

# cn_exchange 是中国挂牌场所；connect venue 是静态参考目录里的香港通道
# venue id。两条都是 northbound（香港投资者北上买 A 股）。
STOCK_CONNECT_MAP: Mapping[str, Any] = {
    "cn": {
        "venues": [
            {
                "venue_id": "SEHKSZSE",
                "venue_name": "Shanghai-HK Stock Connect",
                "connect_direction": "northbound",
                "cn_exchange": "Shanghai Stock Exchange",
            },
            {
                "venue_id": "SEHKSTAR",
                "venue_name": "STAR Connect",
                "connect_direction": "northbound",
                "cn_exchange": "Shanghai STAR Market",
            },
        ],
        "disclosure_connector": None,
        "note": "CN stays an extra market; no new CN disclosure connector (plan §3.4).",
    }
}


def stock_connect_venues_for(market: str) -> List[Dict[str, str]]:
    """Return Stock Connect venue rows for ``cn`` (empty for other markets)."""
    if str(market or "").strip().lower() != "cn":
        return []
    return [
        dict(row) for row in STOCK_CONNECT_MAP["cn"]["venues"]
    ]


def stock_connect_summary() -> Mapping[str, Any]:
    """Readable summary for coverage/docs."""
    venues = STOCK_CONNECT_MAP["cn"]["venues"]
    return {
        "cn_market_role": "extra",
        "connect_venues": venues,
        "disclosure_connector": None,
        "note": str(STOCK_CONNECT_MAP["cn"]["note"]),
    }


__all__ = [
    "STOCK_CONNECT_MAP",
    "stock_connect_summary",
    "stock_connect_venues_for",
]
