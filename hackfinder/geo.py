"""Offline city matching. GeoNames is loaded only by worker-side callers."""
from __future__ import annotations

import difflib
from functools import lru_cache
import re
import unicodedata


def normalize(value: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                            if not unicodedata.combining(c)).split())


@lru_cache(maxsize=1)
def cities():
    import geonamescache

    cache = geonamescache.GeonamesCache()
    countries = cache.get_countries()
    result = []
    for city in cache.get_cities().values():
        result.append({"id": int(city["geonameid"]), "name": city["name"],
                       "ascii_name": normalize(city["name"]), "country": countries[city["countrycode"]]["name"],
                       "country_code": city["countrycode"], "admin1code": city.get("admin1code", ""), "lat": float(city["latitude"]),
                       "lon": float(city["longitude"]), "population": city["population"],
                       "aliases": {normalize(n) for n in [city["name"], *city.get("alternatenames", [])] if len(n) > 2}})
    return sorted(result, key=lambda c: c["population"], reverse=True)


@lru_cache(maxsize=1)
def city_index():
    index = {}
    for city in cities():
        for alias in city["aliases"]:
            index.setdefault(alias, []).append(city)
    return index


# Words that mean "no place"; never geocoded, offline or online.
PLACEHOLDERS = {"online", "virtual", "remote", "worldwide", "global", "anywhere", "tbd", "tba", "test location",
                "test", "n/a", "na", "none", "to be announced", "to be determined", "location tbd", "tbc"}
_SPLIT = re.compile(r"[,;|/()]|\s[-–—]\s")
_SUFFIX = re.compile(r"\s+(urban|rural|district|governorate|province|region|metropolitan|metropolitan area|county|"
                     r"prefecture|municipality|division)$")
_PREFIX = re.compile(r"^(greater|city of)\s+")
# Local or historic names GeoNames lacks as alternates -> a name it has.
ALIASES = {"den haag": "the hague", "'s-gravenhage": "the hague", "bombay": "mumbai", "calcutta": "kolkata",
           "madras": "chennai", "saigon": "ho chi minh city", "new administrative capital": "cairo",
           "new capital": "cairo", "munchen": "munich", "koln": "cologne", "wien": "vienna", "praha": "prague"}
_CA_PROVINCES = {"AB": "01", "BC": "02", "MB": "03", "NB": "04", "NL": "05", "NS": "07", "ON": "08", "PE": "09",
                 "QC": "10", "SK": "11", "YT": "12", "NT": "13", "NU": "14"}


def placeholder(location: str | None) -> bool:
    """True for empty text and markers such as "REMOTE", "TBD" or "Test Location"."""
    return normalize(location or "").strip(" .!-") in PLACEHOLDERS | {""}


def _variants(part: str) -> list[str]:
    """The part itself, then without region words ("bangalore urban" -> "bangalore"), then aliased."""
    out = [part]
    stripped = part
    while True:
        shorter = _PREFIX.sub("", _SUFFIX.sub("", stripped))
        if shorter == stripped or not shorter:
            break
        out.append(stripped := shorter)
    return list(dict.fromkeys([ALIASES.get(v, v) for v in out] + out))


@lru_cache(maxsize=1)
def _keys_by_country():
    result = {}
    for alias, found in city_index().items():
        for code in {c["country_code"] for c in found}:
            result.setdefault(code, []).append(alias)
    return result


def _country_and_state(parts, country):
    """(ISO2 country or None, US state / Canadian province code or None, parts that are not those)."""
    from .regions import _US_STATES, country_code
    code = country_code(country)
    state, rest = None, []
    for i, part in enumerate(parts):
        up = part.upper()
        if len(part) == 2 and i > 0 and up in _US_STATES and code in (None, "US") and not (
                code is None and any(len(p) > 2 and country_code(p) not in (None, "US") for p in parts)):
            state, code = up, "US"
        elif len(part) == 2 and i > 0 and up in _CA_PROVINCES and code in (None, "CA"):
            state, code = up, "CA"
        elif not code and country_code(part) and i == len(parts) - 1:
            code = country_code(part)
        elif not country_code(part) or len(part) == 2:
            rest.append(part)
    return code, state, rest


def _in_state(city, state, code):
    want = _CA_PROVINCES.get(state, state) if code == "CA" else state
    return city["admin1code"] == want


@lru_cache(maxsize=8192)
def match(location: str | None, country: str | None = None):
    """Best GeoNames city for a location text, or None: every comma part and the whole string are tried,
    region words stripped, aliases and typos (only inside a known country) accepted; ties go to population."""
    if placeholder(location):
        return None
    found = _match(location, country)
    last = ([p.strip() for p in _SPLIT.split(normalize(location)) if p.strip()] or [""])[-1]
    if found is None and not country and len(last) == 2:  # "Mumbai, IN": a state code that is also a country code
        found = _match(location, last)
    return found


def _match(location, country):
    text = normalize(location)
    parts = [p.strip() for p in _SPLIT.split(text) if p.strip()]
    code, state, rest = _country_and_state(parts, country)
    index = city_index()

    def found(names):  # a 3-letter alias is usually an airport code ("MSU"): only a real name counts
        return [(len(v), c) for v in names for c in index.get(v, ()) if len(v) > 3 or v == c["ascii_name"]]
    candidates = found(v for part in dict.fromkeys([text, *rest]) for v in _variants(part))
    if not candidates:  # a part that is a country name may also be a city ("Singapore", "Monaco")
        candidates = found(parts)
    if not candidates and len(rest) < 4:
        words = text.split()
        for size in range(min(5, len(words)), 0, -1):
            for i in range(len(words) - size + 1):
                phrase = " ".join(words[i:i + size])
                if len(phrase) > 3:
                    candidates.extend((n, c) for n, c in found([phrase]) if c["ascii_name"] == phrase)  # loose text: real names only
    if not candidates and code:
        for part in rest:
            for close in difflib.get_close_matches(part, _keys_by_country().get(code, ()), n=2, cutoff=0.9) if len(part) > 5 else ():
                candidates.extend((len(close), c) for c in index[close])
    if code:
        candidates = [x for x in candidates if x[1]["country_code"] == code]
    if state:
        candidates = [x for x in candidates if _in_state(x[1], state, code)]
    return max(candidates, key=lambda x: (x[0], x[1]["population"]))[1] if candidates else None


@lru_cache(maxsize=8192)
def geocode(location: str | None, country: str | None = None, format: str = "unknown"):
    if format == "online":
        return None, None
    city = match(location, country)
    return (city["lat"], city["lon"]) if city else (None, None)


def valid_point(lat, lon):
    """(lat, lon) floats when both are real coordinates (not 0,0), else (None, None)."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None, None
    ok = abs(lat) <= 90 and abs(lon) <= 180 and (lat, lon) != (0, 0) and lat == lat and lon == lon
    return (lat, lon) if ok else (None, None)


def locate(event, online=None):
    """(lat, lon, country_code): source coordinates first, then GeoNames, then the cached/online geocoder
    (`online`, a geocoder.Geocoder, exists only on the worker path). country_code is None when not learned here."""
    if event.format == "online":
        return None, None, None
    lat, lon = valid_point(event.signals.get("lat"), event.signals.get("lon"))
    if lat is not None:
        return lat, lon, None
    city = match(event.location, event.country)
    if city:
        return city["lat"], city["lon"], city["country_code"]
    return online.lookup(event) if online else (None, None, None)


def populate(conn):
    if conn.fetchone("SELECT COUNT(*) AS n FROM places")["n"]:
        return
    conn.executemany("""INSERT INTO places (id, name, ascii_name, country, country_code, lat, lon, population)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO NOTHING""",
                     [(c["id"], c["name"], c["ascii_name"], c["country"], c["country_code"],
                       c["lat"], c["lon"], c["population"]) for c in cities()])
