"""CEO.ca (Canada) community connector — live public JSON API.

Collects channel spiels from ``https://new-api.ceo.ca/api/get_spiels`` filtered
to Toronto calendar days. Item URLs point at the channel page
(``https://ceo.ca/{CHANNEL}``); there is no stable per-spiel deep link.
"""

from .connector import CeocaCaConnector, CeocaRequestError
from .parser import (
    CeocaSpielRow,
    filter_spiels_to_toronto_day,
    parse_ceoca_spiel_payload,
    spiel_title,
    toronto_day,
)

__all__ = [
    "CeocaCaConnector",
    "CeocaRequestError",
    "CeocaSpielRow",
    "filter_spiels_to_toronto_day",
    "parse_ceoca_spiel_payload",
    "spiel_title",
    "toronto_day",
]
