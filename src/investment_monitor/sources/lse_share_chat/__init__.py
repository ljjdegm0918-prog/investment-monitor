"""LSE Share Chat (UK) community connector — honest stub after spike.

Live public HTML/JSON collection is **not** wired: ``lse.co.uk`` Share Chat
returns HTTP 403 to automated clients, and ``londonstockexchange.com``
discussion URLs are SPA shells without server-rendered posts (spike
2026-08-11). Do not enable login-wall scraping. ``collect()`` returns an
empty list until a stable public day-filter feed exists.
"""

from .connector import LseShareChatConnector, london_day
from .parser import parse_lse_share_chat_thread_list

__all__ = [
    "LseShareChatConnector",
    "london_day",
    "parse_lse_share_chat_thread_list",
]
