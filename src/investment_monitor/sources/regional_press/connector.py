"""Company-aware mapper for authoritative regional publisher feeds."""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from ...models import CollectionRequest, InformationItem
from .client import RegionalPressClient
from .profiles import RegionalPressProfile

LOGGER = logging.getLogger(__name__)
MAX_LOOKBACK_DAYS = 30
_LEGAL_SUFFIXES = re.compile(
    r"\b(?:incorporated|inc|corporation|corp|company|co|limited|ltd|plc|"
    r"holdings?|group|s\.?a|s\.?e|a\.?g|n\.?v|spa|ab|oyj)\.?$|"
    r"(?:集团股份有限公司|集團股份有限公司|集团有限公司|集團有限公司|"
    r"股份有限公司|股份有限会社|有限责任公司|有限責任公司|有限公司|"
    r"株式会社|株式會社|集团|集團)$",
    flags=re.IGNORECASE,
)
_LEGAL_PREFIXES = re.compile(
    r"^(?:株式会社|株式會社)\s*",
    flags=re.IGNORECASE,
)


class RegionalPressConnector:
    """Collect one reviewed publisher feed and match it to requested companies."""

    max_lookback_days = MAX_LOOKBACK_DAYS
    source_wide_collection = True
    coverage_kind = "feed_snapshot"

    def __init__(
        self,
        profile: RegionalPressProfile,
        client: Optional[RegionalPressClient] = None,
        universe: Optional[Mapping[str, Mapping[str, str]]] = None,
    ) -> None:
        self.profile = profile
        self.name = profile.source
        self.provider = profile.publisher
        self._client = client or RegionalPressClient.from_environment()
        self._universe = dict(
            universe if universe is not None else _identity_map(profile.market)
        )
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_failure_details: Tuple[Mapping[str, str], ...] = ()
        self.last_collection_status = "empty"
        self.last_records_read = 0

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def merge_universe(
        self,
        identities: Mapping[str, Mapping[str, str]],
    ) -> None:
        """Add persisted company names without weakening official identities."""
        for raw_ticker, raw_identity in identities.items():
            ticker = _normalize_ticker(raw_ticker)
            identity = {
                str(key): str(value)
                for key, value in raw_identity.items()
            }
            if ticker and str(identity.get("name") or "").strip():
                self._universe.setdefault(ticker, identity)

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)
        targets = []
        self.last_failure_details = ()
        self.last_collection_status = "empty"
        self.last_records_read = 0
        for raw_ticker in request.tickers:
            if request.market_for(raw_ticker) != self.profile.market:
                continue
            ticker = _normalize_ticker(raw_ticker)
            identity = _identity_for(self._universe, ticker)
            issuer = str(identity.get("name") or "").strip()
            aliases = _company_aliases(identity)
            if not issuer or not aliases:
                message = f"no_universe_identity: {ticker}"
                failures.append((ticker, message))
                continue
            targets.append((ticker, issuer, aliases))

        if not targets:
            self._set_outcome(items, failures, had_valid_targets=False)
            return items

        try:
            records = self._client.fetch_news(
                self.profile,
                request.start_date,
                request.end_date,
            )
        except Exception as error:
            message = str(error) or error.__class__.__name__
            self._last_errors = (("*", message),)
            self.last_failure_details = ({
                "feed": self.profile.feed_scope,
                "url": self.profile.feed_urls[0],
                "message": message,
            },)
            self.last_collection_status = "failure"
            LOGGER.warning(
                "regional_press source=%s ticker=* status=failure error=%s",
                self.profile.source,
                message,
            )
            raise

        self.last_records_read = len(records)
        for ticker, issuer, aliases in targets:
            for record in records:
                matched = _matched_aliases(record, aliases)
                if not matched:
                    continue
                record_id = str(record.get("external_id") or "").strip()
                if not record_id:
                    record_id = hashlib.sha256(
                        str(record["url"]).encode("utf-8")
                    ).hexdigest()
                items.append(
                    InformationItem(
                        source=self.profile.source,
                        source_type="news",
                        external_id=f"{ticker}:{record_id}",
                        tickers=(ticker,),
                        issuer=issuer,
                        published_at=record["published"],
                        title=str(record["title"]),
                        document_type="publisher_news",
                        url=str(record["url"]),
                        collected_at=collected_at,
                        raw_metadata={
                            "provider": "reviewed_publisher_rss",
                            "publisher": self.profile.publisher,
                            "publisher_domain": self.profile.publisher_domain,
                            "feed_url": str(record["feed_url"]),
                            "feed_scope": self.profile.feed_scope,
                            "language": self.profile.language,
                            "stock_code": ticker,
                            "matched_aliases": list(matched),
                            "license_note": self.profile.license_note,
                            "article_body_fetched": False,
                            "source_role": "regional_authoritative_press",
                        },
                        market=self.profile.market,
                        summary=record.get("summary"),
                        effective_at=record["published"],
                    )
                )
        self._set_outcome(items, failures, had_valid_targets=True)
        return items

    def _set_outcome(
        self,
        items: Sequence[InformationItem],
        failures: Sequence[Tuple[str, str]],
        *,
        had_valid_targets: bool,
    ) -> None:
        self._last_errors = tuple(failures)
        self.last_failure_details = tuple({
            "feed": "company_identity",
            "url": "",
            "message": message,
        } for _ticker, message in failures)
        if failures:
            self.last_collection_status = (
                "partial" if had_valid_targets else "failure"
            )
        else:
            self.last_collection_status = "success" if items else "empty"


def _normalize_ticker(value: str) -> str:
    return str(value or "").strip().upper()


def _identity_for(
    universe: Mapping[str, Mapping[str, str]],
    ticker: str,
) -> Mapping[str, str]:
    candidates = (
        ticker,
        ticker.replace(" ", ""),
        ticker.replace("-", ""),
    )
    for candidate in candidates:
        identity = universe.get(candidate)
        if identity:
            return identity
    return {}


def _company_aliases(
    identity: Mapping[str, str],
    *,
    minimum_trimmed_length: int = 4,
) -> Tuple[str, ...]:
    names = []
    for field in ("name", "name_zh", "name_en", "short_name"):
        name = str(identity.get(field) or "").strip()
        if name and name not in names:
            names.append(name)
    values = [(name, 3) for name in names]
    for name in names:
        trimmed = name
        while True:
            reduced = _LEGAL_PREFIXES.sub("", trimmed.strip(" ,.-"))
            reduced = _LEGAL_SUFFIXES.sub(
                "",
                reduced.strip(" ,.-"),
            ).strip(" ,.-")
            if reduced == trimmed:
                break
            trimmed = reduced
        if trimmed and trimmed != name:
            values.append((trimmed, minimum_trimmed_length))
    aliases = []
    for value, minimum_length in values:
        normalized = _normalized_text(value)
        if len(normalized) < minimum_length or normalized in aliases:
            continue
        aliases.append(normalized)
    return tuple(aliases)


def _matched_aliases(
    record: Mapping[str, Any],
    aliases: Sequence[str],
) -> Tuple[str, ...]:
    haystack = _normalized_text(
        f"{record.get('title') or ''} {record.get('summary') or ''}"
    )
    matched = []
    for alias in aliases:
        if _contains_alias(haystack, alias):
            matched.append(alias)
    return tuple(matched)


def _contains_alias(haystack: str, alias: str) -> bool:
    if alias.isascii() and re.fullmatch(r"[a-z0-9 .&-]+", alias):
        return re.search(
            rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
            haystack,
        ) is not None
    return alias in haystack


def _normalized_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _identity_map(market: str) -> Mapping[str, Mapping[str, str]]:
    """Load the existing official/local universe lazily for company names."""
    try:
        if market == "us":
            from ...us_universe import us_universe_name_map
            return _coerce_identity_map(us_universe_name_map())
        if market == "ca":
            from ...ca_universe import ca_universe_name_map
            return _coerce_identity_map(ca_universe_name_map())
        if market == "uk":
            from ...uk_universe import uk_universe_name_map
            return _coerce_identity_map(uk_universe_name_map())
        if market == "kr":
            from ...kr_universe import kr_universe_name_map
            return _coerce_identity_map(kr_universe_name_map())
        if market == "hk":
            from ...hk_universe import hk_universe_name_map
            return _coerce_identity_map(hk_universe_name_map())
        if market == "jp":
            from ...universe.jp_universe import jp_universe_name_map
            return _coerce_identity_map(jp_universe_name_map())
        if market == "tw":
            from ...tw_universe import tw_universe_name_map
            return _coerce_identity_map(tw_universe_name_map())
        if market == "au":
            from ...au_universe import au_universe_name_map
            return _coerce_identity_map(au_universe_name_map())
        if market == "fr":
            from ...universe.fr_universe import fr_universe_name_map
            return _coerce_identity_map(fr_universe_name_map())
        if market == "it":
            from ...universe.it_universe import it_universe_name_map
            return _coerce_identity_map(it_universe_name_map())
        if market == "es":
            from ...universe.es_universe import es_universe_name_map
            return _coerce_identity_map(es_universe_name_map())
        if market == "ch":
            from ...universe.ch_universe import ch_universe_name_map
            return _coerce_identity_map(ch_universe_name_map())
        if market == "at":
            from ...universe.at_universe import at_universe_name_map
            return _coerce_identity_map(at_universe_name_map())
        if market == "no":
            from ...universe.no_universe import no_universe_name_map
            return _coerce_identity_map(no_universe_name_map())
        if market == "pt":
            from ...universe.pt_universe import pt_universe_name_map
            return _coerce_identity_map(pt_universe_name_map())
        if market == "se":
            from ...universe.se_universe import se_universe_name_map
            return _coerce_identity_map(se_universe_name_map())
        if market == "hu":
            from ...universe.hu_universe import hu_universe_name_map
            return _coerce_identity_map(hu_universe_name_map())
        if market in {"ee", "lv", "lt"}:
            from ...universe.nasdaq_baltic_universe import baltic_universe_name_map
            return _coerce_identity_map(baltic_universe_name_map(market))
        if market == "sg":
            from ...universe.sg_universe import sg_universe_name_map
            return _coerce_identity_map(sg_universe_name_map())
        if market == "il":
            from ...universe.il_universe import il_universe_name_map
            return _coerce_identity_map(il_universe_name_map())
        if market == "mx":
            from ...universe.mx_universe import mx_universe_name_map
            return _coerce_identity_map(mx_universe_name_map())
        if market == "in":
            from ...universe.in_universe import in_universe_name_map
            return _coerce_identity_map(in_universe_name_map())
        if market == "be":
            from ...universe.be_universe import be_universe_name_map
            return _coerce_identity_map(be_universe_name_map())
        if market == "de":
            from ...universe.de_universe import de_universe_name_map
            return _coerce_identity_map(de_universe_name_map())
        if market == "nl":
            from ...universe.nl_universe import nl_universe_name_map
            return _coerce_identity_map(nl_universe_name_map())
        if market == "pl":
            from ...universe.pl_universe import pl_universe_name_map
            return _coerce_identity_map(pl_universe_name_map())
    except (OSError, ValueError, RuntimeError) as error:
        LOGGER.warning(
            "regional_press market=%s universe_unavailable error=%s",
            market,
            error,
        )
    return {}


def _coerce_identity_map(
    value: object,
) -> Mapping[str, Mapping[str, str]]:
    if not isinstance(value, Mapping):
        return {}
    result = {}
    for raw_key, raw_identity in value.items():
        if not isinstance(raw_identity, Mapping):
            continue
        key = str(raw_key).strip().upper()
        if not key:
            continue
        result[key] = {
            str(field): str(field_value)
            for field, field_value in raw_identity.items()
        }
    return result
