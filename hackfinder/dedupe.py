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


# Words that don't identify a place: country names/codes and generic venue words. Sources write the
# same venue very differently ("Eindhoven, NL" vs "HTC 31 - Holst Centre, Eindhoven, Netherlands").
_PLACE_NOISE = {
    "the", "and", "of", "de", "la", "le", "der", "van", "building", "centre", "center", "campus", "hall",
    "room", "floor", "street", "st", "road", "rd", "avenue", "ave", "university", "college", "school",
    "office", "hub", "space", "online", "virtual", "remote", "tbd", "tba", "venue", "city",
    "nl", "netherlands", "nederland", "us", "usa", "united", "states", "america", "uk", "kingdom",
    "gb", "england", "de", "germany", "deutschland", "fr", "france", "in", "india", "es", "spain",
    "it", "italy", "ca", "canada", "be", "belgium", "ch", "switzerland", "se", "sweden", "pl", "poland",
    "pt", "portugal", "ie", "ireland", "au", "australia", "sg", "singapore", "br", "brazil", "jp", "japan",
}


# Native and English city names count as the same place word ("Garching bei München" ~ "Munich").
_PLACE_ALIAS = {
    "munchen": "munich", "muenchen": "munich", "koln": "cologne", "koeln": "cologne", "nurnberg": "nuremberg",
    "nuernberg": "nuremberg", "wien": "vienna", "praha": "prague", "warszawa": "warsaw", "krakow": "cracow",
    "milano": "milan", "roma": "rome", "torino": "turin", "napoli": "naples", "firenze": "florence",
    "lisboa": "lisbon", "bruxelles": "brussels", "brussel": "brussels", "antwerpen": "antwerp",
    "gent": "ghent", "haag": "hague", "genf": "geneva", "geneve": "geneva", "zurich": "zurich",
    "kobenhavn": "copenhagen", "goteborg": "gothenburg", "athina": "athens", "bei": "the",
}


def _place_tokens(location: str) -> set[str]:
    text = unicodedata.normalize("NFKD", location).encode("ascii", "ignore").decode().casefold()
    tokens = (_PLACE_ALIAS.get(t, t) for t in re.findall(r"[a-z]{3,}", text))
    return {t for t in tokens if t not in _PLACE_NOISE}


def _same_place(left: str, right: str) -> bool:
    """Same place when the strings share a real place word (usually the city)."""
    if left.casefold() == right.casefold():
        return True
    a, b = _place_tokens(left), _place_tokens(right)
    return not a or not b or bool(a & b)


_YEAR = re.compile(r"^(?:19|20)\d\d$")
# Words too generic to identify an event on their own ("AI Hackathon" in two cities is two events).
_GENERIC = {"hack", "hacks", "hackathon", "hackathons", "build", "builders", "buildathon", "day", "night", "ai",
            "the", "and", "for", "with", "x", "a", "of", "in", "on", "challenge", "jam", "game", "ctf", "edition"}


def _numbers(tokens: set[str]) -> set[str]:
    """Edition numbers; years are dropped ("Hoya Hacks" ~ "Hoya Hacks 2027")."""
    return {t for t in tokens if t.isdigit() and not _YEAR.match(t)}


def _days_apart(left: Event, right: Event) -> int:
    """Gap in days between the two [start, end] ranges (0 when they overlap)."""
    a0, b0 = left.start.date(), right.start.date()
    a1, b1 = (left.end or left.start).date(), (right.end or right.start).date()
    return max(0, (max(a0, b0) - min(a1, b1)).days)


def _point(event: Event):
    try:
        return float(event.signals["lat"]), float(event.signals["lon"])
    except (KeyError, TypeError, ValueError):
        from .geo import geocode  # offline GeoNames lookup, no network
        lat, lon = geocode(event.location, event.country)
        return (lat, lon) if lat is not None else None


def _km(left: Event, right: Event) -> float | None:
    """Distance between the two venues when both resolve to a point, else None."""
    import math
    p, q = _point(left), _point(right)
    if not p or not q:
        return None
    (la1, lo1), (la2, lo2) = p, q
    h = math.sin(math.radians(la2 - la1) / 2) ** 2 + math.cos(math.radians(la1)) * math.cos(math.radians(la2)) *         math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def _same(left: Event, right: Event) -> bool:
    if normalize_url(left.url) == normalize_url(right.url):
        return True
    if not left.start or not right.start:
        return False
    a, b = _tokens(left.title), _tokens(right.title)
    if not a or not b:
        return False
    # Distinct numbered/local editions must survive fuzzy matching; a missing number or a year is not a conflict.
    na, nb = _numbers(a), _numbers(b)
    if na and nb and na != nb:
        return False
    ya, yb = {t for t in a if _YEAR.match(t)}, {t for t in b if _YEAR.match(t)}
    if ya and yb and ya != yb:
        return False
    core_a = {t for t in a if not _YEAR.match(t)}
    core_b = {t for t in b if not _YEAR.match(t)}
    # Same distinctive name: aggregators disagree on dates (registration vs event days) and venue vs city.
    exact = core_a == core_b and bool(core_a - _GENERIC - set(na))
    if _days_apart(left, right) > (7 if exact else 1):
        return False
    if left.location and right.location and not _same_place(left.location, right.location):
        km = _km(left, right)
        if km is not None:
            if km > 80:
                return False
        elif not exact or _days_apart(left, right) > 1:
            return False
    if exact:
        return True
    return token_set_similarity(core_a, core_b) >= 0.88


def _authority(event: Event) -> int:
    return {"hackathoncom": 100, "meetup": 30, "unstop": 20, "mlh": 15}.get(event.source, 0)


def _signals(event: Event) -> dict:
    from .score import COUNTS, extract

    result = extract(event)
    if event.participants is not None and not any(k in result for k in COUNTS - {"capacity"}):
        result["participants"] = event.participants
    for key in COUNTS & result.keys():
        if not isinstance(result[key], dict):
            result[key] = {event.source: result[key]}
    return result


def merge_signals(left: dict, right: dict) -> dict:
    result = dict(left)
    for key, value in right.items():
        if key not in result:
            result[key] = value
        elif isinstance(value, dict) and isinstance(result[key], dict):
            result[key] = {**value, **result[key]}
        elif isinstance(value, list) and isinstance(result[key], list):
            result[key] = list(dict.fromkeys(result[key] + value))
        elif isinstance(value, bool) and isinstance(result[key], bool):
            result[key] = result[key] or value
    return result


def dedupe(events: list[Event]) -> list[Event]:
    result: list[Event] = []
    # Process authority first so the canonical identity stays stable.
    for event in sorted(events, key=_authority):
        match = next((i for i, old in enumerate(result) if _same(old, event)), None)
        if match is None:
            result.append(event.model_copy(deep=True, update={"signals": _signals(event)}))
            continue
        old = result[match]
        updates = {}
        for field in Event.model_fields:
            if field in {"source", "source_id", "url", "also_on", "fetched_at", "signals"}:
                continue
            value = getattr(old, field)
            if value is None or value == "" or value == [] or value == "unknown":
                other = getattr(event, field)
                if other is not None:
                    updates[field] = other
        if "kind" in updates:
            updates["confidence"] = event.confidence
            updates["classified_by"] = event.classified_by
        updates["signals"] = merge_signals(old.signals, _signals(event))
        updates["also_on"] = sorted((set(old.also_on) | set(event.also_on) | {event.source}) - {old.source})
        result[match] = old.model_copy(update=updates)
    return result
