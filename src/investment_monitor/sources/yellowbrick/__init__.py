"""Yellowbrick Investing (US) community connector — honest stub after spike.

Live public collection is **not** wired: the product domain ``ybrick.co`` is
dead (DNS/transport failure), ``joinyellowbrick.com`` serves a marketing
landing page with all content paths (``/stocks``, ``/ideas``, ``/pitches``)
returning HTTP 404, and the Substack is a waitlist capture page with no
public posts (spike 2026-08-11). Do not enable login-wall or Supabase-key
scraping. ``collect()`` returns an empty list until a stable public
login-free feed exists.

This connector intentionally targets **Yellowbrick Investing**
(``joinyellowbrick.com`` / ``ybrick.co``), not the unrelated SQL data
platform vendor at ``yellowbrick.com`` whose corporate blog RSS is live but
out of scope for this community seat.
"""

from .connector import YellowbrickConnector

__all__ = [
    "YellowbrickConnector",
]
