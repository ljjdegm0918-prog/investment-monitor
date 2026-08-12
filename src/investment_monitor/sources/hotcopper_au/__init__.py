"""HotCopper (Australia) community connector — honest stub after spike.

Live public HTML/JSON collection is **not** wired: automated clients receive
HTTP 403 Cloudflare challenges on ``https://hotcopper.com.au/asx/{ticker}/``
(and the site home). Do not enable login-wall scraping. ``collect()`` returns
an empty list until a stable public day-filter feed exists.
"""

from .connector import HotCopperAuConnector
from .parser import parse_hotcopper_thread_list

__all__ = [
    "HotCopperAuConnector",
    "parse_hotcopper_thread_list",
]
