"""URL identity, conservative title/date matching, and provenance merging."""
from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from .models import Event

TRACKING = {"fbclid", "gclid", "msclkid", "ref", "referrer", "source", "mc_cid", "mc_eid"}


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    if host == "lu.ma":
        host = "luma.com"
    if parts.port and parts.port not in (80, 443):
        host += f":{parts.port}"
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                   if not k.lower().startswith("utm_") and k.lower() not in TRACKING)
    return urlunsplit(("https", host, parts.path.rstrip("/"), urlencode(query), ""))


def event_key(event: Event) -> str:
    return normalize_url(event.url)


def _tokens(title: str) -> set[str]:
    title = unicodedata.normalize("NFKC", title).casefold()
    return set(re.findall(r"[^\W_]+", title))


def token_set_similarity(a: set[str], b: set[str]) -> float:
    common = a & b
    left = " ".join(sorted(common) + sorted(a - b))
    right = " ".join(sorted(common) + sorted(b - a))
    scores = [SequenceMatcher(None, left, right).ratio()]
    if common:
        shared = " ".join(sorted(common))
        scores.extend((SequenceMatcher(None, shared, left).ratio(),
                       SequenceMatcher(None, shared, right).ratio()))
    return max(scores)


def _same(left: Event, right: Event) -> bool:
    if normalize_url(left.url) == normalize_url(right.url):
        return True
    if not left.start or not right.start or abs((left.start.date() - right.start.date()).days) > 1:
        return False
    # Distinct numbered/local editions must survive fuzzy matching.
    a, b = _tokens(left.title), _tokens(right.title)
    if {t for t in a if t.isdigit()} != {t for t in b if t.isdigit()}:
        return False
    if left.location and right.location and left.location.casefold() != right.location.casefold():
        return False
    if not a or not b:
        return False
    return token_set_similarity(a, b) >= 0.88


def _authority(event: Event) -> int:
    return {"hackathoncom": 100, "meetup": 30, "unstop": 20, "mlh": 15}.get(event.source, 0)


def dedupe(events: list[Event]) -> list[Event]:
    result: list[Event] = []
    # Process authority first so the canonical identity stays stable.
    for event in sorted(events, key=_authority):
        match = next((i for i, old in enumerate(result) if _same(old, event)), None)
        if match is None:
            result.append(event.model_copy(deep=True))
            continue
        old = result[match]
        updates = {}
        for field in Event.model_fields:
            if field in {"source", "source_id", "url", "also_on", "fetched_at"}:
                continue
            value = getattr(old, field)
            if value is None or value == "" or value == [] or value == "unknown":
                other = getattr(event, field)
                if other is not None:
                    updates[field] = other
        if "kind" in updates:
            updates["confidence"] = event.confidence
            updates["classified_by"] = event.classified_by
        updates["also_on"] = sorted((set(old.also_on) | set(event.also_on) | {event.source}) - {old.source})
        result[match] = old.model_copy(update=updates)
    return result
