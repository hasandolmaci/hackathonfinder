"""Offline city matching. GeoNames is loaded only by worker-side callers."""
from __future__ import annotations

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
                       "country_code": city["countrycode"], "lat": float(city["latitude"]),
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


@lru_cache(maxsize=8192)
def geocode(location: str | None, country: str | None = None, format: str = "unknown"):
    if format == "online" or not location or normalize(location) in {"online", "virtual", "remote", "worldwide"}:
        return None, None
    text = normalize(location)
    parts = [p.strip() for p in re.split(r"[,;|/()]", text) if p.strip()]
    country_hint = normalize(country or "")
    countries = {normalize(c["country"]): c["country_code"] for c in cities()}
    countries.update({c["country_code"].lower(): c["country_code"] for c in cities()})
    countries.update({"usa": "US", "uk": "GB", "south korea": "KR"})
    code = countries.get(country_hint) or next((countries[p] for p in reversed(parts) if p in countries), None)
    candidates = []
    index = city_index()
    for part in parts:
        if part in index:
            candidates.extend((len(part), c) for c in index[part])
    if not candidates:
        words = text.split()
        for size in range(min(5, len(words)), 0, -1):
            for i in range(len(words) - size + 1):
                phrase = " ".join(words[i:i + size])
                if phrase in index and len(phrase) > 3:
                    candidates.extend((len(phrase), c) for c in index[phrase])
    if code:
        candidates = [(length, c) for length, c in candidates if c["country_code"] == code]
    if not candidates:
        return None, None
    city = max(candidates, key=lambda item: (item[0], item[1]["population"]))[1]
    return city["lat"], city["lon"]


def populate(conn):
    if conn.fetchone("SELECT COUNT(*) AS n FROM places")["n"]:
        return
    conn.executemany("""INSERT INTO places (id, name, ascii_name, country, country_code, lat, lon, population)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO NOTHING""",
                     [(c["id"], c["name"], c["ascii_name"], c["country"], c["country_code"],
                       c["lat"], c["lon"], c["population"]) for c in cities()])
