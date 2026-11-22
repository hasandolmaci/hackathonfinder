"""Cached OpenStreetMap Nominatim fallback for places GeoNames cannot place. Worker/rescore path only:
the web app never imports this module (httpx is imported lazily, inside the request).

Follows https://operations.osmfoundation.org/policies/nominatim/: at most one request per second, a descriptive
User-Agent, every answer cached (misses 30 days, errors 1 day), no bulk re-queries. HF_GEOCODE_ONLINE=0 switches it off;
HF_GEOCODE_MAX caps the new lookups per run (default 150).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
import re
import time

from . import db
from .geo import placeholder, valid_point

log = logging.getLogger(__name__)
URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "Hackfinder/1.0 (open-source hackathon finder)"
MIN_INTERVAL = 1.1  # seconds between requests
COARSE = {"country", "state", "region", "province", "county", "state_district", "continent"}  # too vague for radius search
TTL = {"miss": timedelta(days=30), "error": timedelta(days=1)}
_sleep, _clock = time.sleep, time.monotonic  # module attributes so tests can replace them


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enabled() -> bool:
    return os.getenv("HF_GEOCODE_ONLINE", "1").strip() != "0"


def normalize_query(text: str) -> str:
    """Lowercase, drop parenthesised asides, collapse whitespace and stray punctuation: the cache key."""
    text = re.sub(r"\([^)]*\)", " ", text.casefold())
    return re.sub(r"\s+", " ", re.sub(r"\s*,\s*", ", ", text)).strip(" ,;.-")


def _query(event) -> tuple[str, str | None]:
    """(normalized query, ISO2 country code or None); the country is appended when the text lacks it."""
    from .regions import _from_location, country_code
    text = event.location if not placeholder(event.location) else event.signals.get("address")
    if not text or placeholder(text):
        return "", None
    code = country_code(event.country) or _from_location(text)
    query = normalize_query(str(text))
    if not code and len(query) <= 4 and not event.country:  # "XDC": an acronym with no country matches anything
        return "", None
    country = normalize_query(event.country or "")
    if country and not placeholder(country) and country not in query:
        query = f"{query}, {country}"
    return query, code


class Geocoder:
    """One per run: holds the DB connection, the per-run request budget and the rate limiter."""

    def __init__(self, conn: db.Connection, max_lookups: int | None = None):
        self.conn = conn
        self.max = int(os.getenv("HF_GEOCODE_MAX", "150")) if max_lookups is None else max_lookups
        self.requests = 0
        self.stopped = False  # set after a refusal (HTTP 403/429/5xx): no more requests this run
        self._last: float | None = None

    def _cached(self, key: str):
        row = self.conn.fetchone("SELECT lat, lon, country_code, status, fetched_at FROM geocode_cache WHERE query = ?", (key,))
        if row and row["status"] != "ok":
            if utcnow() - datetime.fromisoformat(row["fetched_at"]) >= TTL[row["status"]]:
                return None
        return row

    def _save(self, key, status, lat=None, lon=None, code=None, name=None):
        self.conn.execute("""INSERT INTO geocode_cache (query, lat, lon, country_code, display_name, status, fetched_at)
                             VALUES (?, ?, ?, ?, ?, ?, ?)
                             ON CONFLICT (query) DO UPDATE SET lat = excluded.lat, lon = excluded.lon,
                                 country_code = excluded.country_code, display_name = excluded.display_name,
                                 status = excluded.status, fetched_at = excluded.fetched_at""",
                          (key, lat, lon, code, name, status, utcnow().isoformat()))

    def _fetch(self, query: str, code: str | None) -> dict | None:
        import httpx
        if self._last is not None:
            _sleep(max(0.0, MIN_INTERVAL - (_clock() - self._last)))
        self._last = _clock()
        self.requests += 1
        params = {"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1}
        if code:
            params["countrycodes"] = code.lower()
        response = httpx.get(URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
        if response.status_code in (403, 429) or response.status_code >= 500:
            self.stopped = True
        response.raise_for_status()
        rows = response.json()
        return rows[0] if rows else None

    def lookup(self, event) -> tuple[float | None, float | None, str | None]:
        """(lat, lon, country_code) from the cache, else (within the run budget) from Nominatim; Nones otherwise.
        A result whose country contradicts the event's known country is rejected."""
        query, known = _query(event)
        if not query:
            return None, None, None
        key = f"{query} @{known}" if known else query
        row = self._cached(key)
        if row is None:
            if not enabled() or self.stopped or self.requests >= self.max:
                return None, None, None
            try:
                hit = self._fetch(query, known)
            except Exception as exc:  # network, HTTP or JSON failure: remember it for a day, never raise
                log.warning("geocode %r failed: %s", query, type(exc).__name__)
                self._save(key, "error")
                return None, None, None
            lat, lon = valid_point((hit or {}).get("lat"), (hit or {}).get("lon"))
            if lat is None or (hit or {}).get("addresstype") in COARSE:
                self._save(key, "miss")
                return None, None, None
            found = ((hit.get("address") or {}).get("country_code") or "").upper() or None
            self._save(key, "ok", lat, lon, found, hit.get("display_name"))
            row = {"status": "ok", "lat": lat, "lon": lon, "country_code": found}
        if row["status"] != "ok":
            return None, None, None
        if known and row["country_code"] and row["country_code"] != known:
            return None, None, None
        return row["lat"], row["lon"], row["country_code"]
