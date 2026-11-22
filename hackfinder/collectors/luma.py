"""Public discovery JSON. Undocumented website endpoint; no login or key.

Scoped collector. Search returns at most 50 entries per request and ignores
pagination, so coverage comes from many small scopes:
- global / online queries (English plus multilingual spellings),
- query x Luma place (explicit place IDs avoid the default feed's IP-based location bias),
- "hackathon <city>" for cities without a place,
- query x discover category (global only: with a place ID the category is ignored),
- a final "calendars" scope that lists the upcoming events of every organizer calendar seen
  in the earlier scopes plus the seeds in luma_calendars.json (api.lu.ma/calendar/get-items,
  paginated by cursor, so a calendar is read completely).
A scope that returns exactly 50 is saturated and logged.

Measured 2026-11-22: the discover endpoint ignores offset/page/cursor, pagination_limit > 50,
period=future, date parameters, sort and event_type; latitude/longitude only nudge the ranking.
"""
import json
import logging
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import httpx

from hackfinder.models import Event
from ._signals_util import geo
from ._vertical_util import MAX_PAGES, client, dt, plain, polite_json, robots, upcoming, walk, warn_limit

SOURCE = {"id": "luma", "name": "Luma", "url": "https://luma.com/discover",
          "method": "api", "default_kind": "mixed"}
RANKED_SEARCH = True  # 50-result ranked searches: absence never proves an event is gone
API = "https://api.lu.ma"
PAGE = 50
QUERIES = ["hackathon", "hack", "buildathon", "datathon", "game jam", "ideathon"]
# Extra global queries, kept only because each found events no other scope found (measured).
MORE_QUERIES = ["hackatón", "hackaton", "hakaton", "хакатон", "ハッカソン", "해커톤", "黑客松", "hackathon IA",
                "AI build day", "codefest", "hack night", "hackathon 2026", "hackathon 2027", "agent hackathon",
                "hackathon student", "vibe coding", "capture the flag", "build weekend"]
ONLINE_MORE = ["hackatón", "hakaton", "хакатон", "ハッカソン", "해커톤", "黑客松", "AI build day", "hackathon 2026"]
# Per place only "hackathon" and "hack" (the other queries add almost nothing in small places); the
# big scenes, where a query returns a full 50, also get the rest of QUERIES.
PLACE_QUERIES = QUERIES[:2]
BIG_PLACES = ["nyc", "sf", "london", "berlin", "paris", "bengaluru", "singapore", "chicago", "toronto", "la", "boston"]
# Discover categories (slug) searched globally; place + category returned the place's results unchanged.
CATEGORIES = ["tech", "ai", "arts", "climate", "crypto", "family"]
CATEGORY_QUERIES = ["hack", "hackathon"]
CALENDARS_FILE = Path(__file__).with_name("luma_calendars.json")
CALENDAR_BUDGET = 15 * 60  # Seconds for the whole "calendars" scope; the busiest calendars go first.
QUICK_PLACES = ["sf", "nyc", "london", "berlin", "amsterdam", "paris", "bengaluru", "singapore"]
# Cities without a Luma place (and a few extra); searched as "hackathon <city>".
CITY_QUERIES = [
    "Utrecht", "Eindhoven", "Rotterdam", "The Hague", "Delft", "Leiden", "Groningen", "Nijmegen",
    "Enschede", "Maastricht", "Tilburg", "Breda", "Haarlem", "Arnhem", "Amersfoort", "Den Haag", "Den Bosch",
    "'s-Hertogenbosch", "Antwerp", "Ghent",
    "Cologne", "Stuttgart", "Dusseldorf", "Leipzig", "Dresden", "Nuremberg", "Lyon", "Toulouse", "Nice",
    "Lille", "Krakow", "Wroclaw", "Gdansk", "Brno", "Basel", "Graz", "Porto", "Valencia", "Seville",
    "Gothenburg", "Tallinn", "Riga", "Vilnius", "Bucharest", "Sofia", "Athens", "Belgrade", "Zagreb",
    "Kyiv", "Tbilisi", "Edinburgh", "Manchester", "Bristol", "Cambridge", "Oxford", "Ankara", "Izmir",
    "Pune", "Hyderabad", "Chennai", "Kolkata", "Ahmedabad", "Jaipur", "Kochi", "Gurgaon", "Noida",
    "Chandigarh", "Indore", "Colombo", "Kathmandu", "Dhaka", "Karachi", "Lahore", "Islamabad", "Lagos",
    "Accra", "Abuja", "Kampala", "Kigali", "Johannesburg", "Casablanca", "Tunis", "Cairo", "Riyadh",
    "Abu Dhabi", "Doha", "Montevideo", "Santiago", "Lima", "Quito", "Guadalajara", "Monterrey",
    "Cordoba", "Shanghai", "Beijing", "Shenzhen", "Hanoi", "Da Nang", "Bali", "Penang", "Cebu", "Perth",
    "Wellington", "San Jose", "Palo Alto", "Oakland", "Berkeley", "Orlando", "Nashville", "Charlotte",
    "Columbus", "Indianapolis", "St. Louis", "Kansas City", "Baltimore", "Boulder", "Ann Arbor",
    "Cleveland", "Tampa", "Ottawa", "Winnipeg",
]
# Words that mark a hackathon-like event in the name or description.
RELEVANT = re.compile(r"hack|buildathon|datathon|makeathon|ideathon|game jam|codefest|build day|build night|"
                      r"ハッカソン|해커톤|hackaton|hakaton", re.I)
log = logging.getLogger(__name__)
_places: dict[str, str] = {}
_categories: dict[str, str] = {}
_calendars: dict[str, dict] = {}  # api_id -> {"name", "hits"}: calendars that posted a relevant event this run
_blocked = 0
_checked = False


def _signals(entry, raw, hosts, calendar):
    """Quality evidence for the Hackfinder Score; only what the API really returns. Discover entries
    carry no ticket capacity (only spots_remaining), so there is no "capacity"."""
    ticket = entry.get("ticket_info") or {}
    price = ticket.get("price") or {}
    cents = price.get("cents") if isinstance(price.get("cents"), (int, float)) else 0
    paid = ticket.get("is_free") is False or cents > 0
    guests = entry.get("guest_count")
    text = raw.get("description") or raw.get("description_md") or " ".join(
        x.get("text", "") for x in walk(entry.get("description_mirror")) if x.get("type") == "text")
    signals = {
        "guests": guests if isinstance(guests, int) and guests > 0 and not raw.get("hide_rsvp") else None,
        "hosts": [x["name"] for x in entry.get("hosts", []) if x.get("name")] or None,
        "calendar_id": calendar.get("api_id"),
        "calendar_name": calendar.get("name"),
        "paid_entry": paid if ticket else None,
        "entry_fee": f"{cents / 100:.2f} {str(price.get('currency') or '').upper()}".strip() if cents > 0 else None,
        "featured": True if entry.get("featured_guests") else None,
        "text": " ".join(str(text or "").split())[:3000] or None,
    }
    info = raw.get("geo_address_info") or {}
    coordinate = raw.get("coordinate") or {}
    signals.update(geo(coordinate.get("latitude", raw.get("geo_latitude")), coordinate.get("longitude", raw.get("geo_longitude")),
                       info.get("full_address") or ", ".join(str(x) for x in (info.get("address"), info.get("city")) if x)))
    return {k: v for k, v in signals.items() if v is not None}


def _event(entry):
    raw = entry.get("event") or {}
    if not raw.get("name") or not raw.get("url"):
        return None
    start, end = dt(raw.get("start_at")), dt(raw.get("end_at"))
    if not upcoming(start, end):
        return None
    geo = raw.get("geo_address_info") or {}
    location = ", ".join(str(x) for x in [geo.get("city"), geo.get("country")] if x) or None
    mode = raw.get("location_type")
    fmt = {"online": "online", "virtual": "online", "hybrid": "hybrid", "offline": "in-person"}.get(mode, "unknown")
    tickets = entry.get("ticket_types") or []
    virtual_tickets = [bool(re.search(r"\b(virtual|online|remote)\b", (t.get("name") or "") + " " + (t.get("description") or ""), re.I))
                       for t in tickets]
    if virtual_tickets and any(virtual_tickets):
        fmt = "online" if all(virtual_tickets) else "hybrid"
    # An obfuscated address is not evidence of an online event.
    hosts = ", ".join(x["name"] for x in entry.get("hosts", []) if x.get("name"))
    calendar = entry.get("calendar") or {}
    title = raw["name"]
    tags = [tag for word, tag in [(" ai", "ai"), ("agent", "ai"), ("web3", "web3"), ("climate", "climate")]
            if word in (" " + title).lower()]
    return Event(signals=_signals(entry, raw, hosts, calendar),
                 source="luma", source_id=raw.get("api_id") or entry.get("api_id"),
                 title=title, url=urljoin("https://luma.com/", raw["url"]),
                 description=plain(raw.get("description") or raw.get("description_md") or " ".join(
                     x.get("text", "") for x in walk(entry.get("description_mirror")) if x.get("type") == "text")),
                 image=raw.get("cover_url"), start=start, end=end,
                 format=fmt, location=None if fmt == "online" else location,
                 country=None if fmt == "online" else geo.get("country"),
                 participants=entry.get("guest_count"), organizer=hosts or calendar.get("name"),
                 tags=list(dict.fromkeys(tags)), kind="unknown")


def _fold(text):
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower().strip()


# English/Dutch spellings of the same city: a query for either one accepts events placed under any of them.
CITY_ALIASES = [{"the hague", "den haag", "'s-gravenhage", "s-gravenhage"}, {"'s-hertogenbosch", "s-hertogenbosch", "den bosch"}]


def _in_city(entry, city):
    geo = (entry.get("event") or {}).get("geo_address_info") or {}
    cities = [geo.get("city"), geo.get("full_address")]
    cities += [x.get("city") for x in (geo.get("localized") or {}).values()]
    names = next((a for a in CITY_ALIASES if _fold(city) in a), {_fold(city)})
    return any(n in _fold(x) for n in names for x in cities if x)


def _get(c, params):
    global _blocked, _checked
    if _blocked >= 2:
        raise RuntimeError("blocked: Luma refused repeated requests; stopping the scope set")
    if not _checked:
        robots(c, API + "/discover/get-paginated-events")
        _checked = True
    try:
        data = polite_json(c, API + params.pop("_path", "/discover/get-paginated-events"), params=params)
        _blocked = 0
        return data
    except RuntimeError as exc:
        _blocked += str(exc).startswith("blocked")
        raise


def _load_places(c):
    if not _places:
        bootstrap = _get(c, {"_path": "/discover/bootstrap-page"})
        for x in bootstrap.get("places", []):
            place = x.get("place", x)
            if place.get("slug") and place.get("api_id"):
                _places[place["slug"]] = place["api_id"]
        for x in bootstrap.get("categories", []):
            category = x.get("category", x)
            if category.get("slug") and category.get("api_id"):
                _categories[category["slug"]] = category["api_id"]
    return _places


def seed_calendars() -> dict[str, str]:
    """api_id -> name of the known hackathon-heavy calendars (luma_calendars.json, updated by hand)."""
    try:
        data = json.loads(CALENDARS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("cannot read %s", CALENDARS_FILE.name)
        return {}
    return {x["api_id"]: x.get("name") or x.get("slug") or "" for x in data.get("calendars", []) if x.get("api_id")}


def calendar_order(seeds: dict[str, str], seen: dict[str, dict]) -> list[tuple[str, str]]:
    """Calendars to crawl: seeds first, then the calendars seen this run, busiest first."""
    rest = sorted((k for k in seen if k not in seeds), key=lambda k: -seen[k]["hits"])
    return list(seeds.items()) + [(k, seen[k]["name"]) for k in rest]


def scopes(pass_name: str) -> list[str]:
    online = [f"{kind}:{q}" for q in QUERIES for kind in ("global", "online")]
    if pass_name != "full":
        return [s for s in online if s.endswith(":hackathon")] + [f"place:{p}:hackathon" for p in QUICK_PLACES]
    with client(timeout=6) as c:
        places = _load_places(c)
    return (online + [f"global:{q}" for q in MORE_QUERIES] + [f"online:{q}" for q in ONLINE_MORE]
            + [f"place:{p}:{q}" for p in places for q in (QUERIES if p in BIG_PLACES else PLACE_QUERIES)]
            + [f"city:{city}" for city in CITY_QUERIES]
            + [f"cat:{slug}:{q}" for slug in CATEGORIES if slug in _categories for q in CATEGORY_QUERIES]
            + ["calendars"])


def relevant_events(entries, city=None) -> dict[str, Event]:
    """Entries -> upcoming relevant events by api_id. Search is fuzzy, so the keyword filter keeps the
    raw evidence for the classifier. Calendars that posted one are remembered for the calendars scope."""
    events = {}
    for entry in entries:
        raw = entry.get("event") or {}
        if not RELEVANT.search(raw.get("name", "") + " " + (raw.get("description") or "")):
            continue
        if city and not _in_city(entry, city):
            continue
        event = _event(entry)
        if event and event.source_id:
            events[event.source_id] = event
            calendar = entry.get("calendar") or {}
            if calendar.get("api_id"):
                seen = _calendars.setdefault(calendar["api_id"], {"name": calendar.get("name") or "", "hits": 0})
                seen["hits"] += 1
    return events


def _collect_calendars() -> list[Event]:
    """Every upcoming event of every known calendar (cursor pagination), relevance-filtered.
    Stops at CALENDAR_BUDGET seconds and logs how many calendars were left."""
    order = calendar_order(seed_calendars(), _calendars)
    started, events, done = time.monotonic(), {}, 0
    with client(timeout=10) as c:
        for api_id, name in order:
            if time.monotonic() - started > CALENDAR_BUDGET:
                log.warning("calendars budget of %ds reached: %d of %d calendars crawled", CALENDAR_BUDGET, done, len(order))
                break
            cursor = None
            for _ in range(MAX_PAGES):
                params = {"_path": "/calendar/get-items", "calendar_api_id": api_id, "period": "future",
                          "pagination_limit": PAGE}
                if cursor:
                    params["pagination_cursor"] = cursor
                try:
                    data = _get(c, params)
                except httpx.HTTPStatusError as exc:  # a deleted or private calendar must not stop the rest
                    log.info("calendar %s (%s) skipped: HTTP %s", api_id, name, exc.response.status_code)
                    break
                if not isinstance(data.get("entries"), list):
                    raise RuntimeError("Luma calendar response changed: missing entries")
                events.update(relevant_events(data["entries"]))
                cursor = data.get("next_cursor")
                if not (data.get("has_more") and cursor):
                    break
            else:
                warn_limit(__name__, f"calendar {api_id}")
            done += 1
    log.info("calendars: %d crawled, %d relevant upcoming events", done, len(events))
    return list(events.values())


def collect_scope(scope: str) -> list[Event]:
    """One request (Luma caps a response at 50 entries), except "calendars", which pages through each calendar."""
    if scope == "calendars":
        return _collect_calendars()
    kind, _, rest = scope.partition(":")
    params = {"pagination_limit": PAGE}
    city = None
    with client(timeout=6) as c:
        if kind == "place":
            slug, _, query = rest.partition(":")
            params.update(query=query, discover_place_api_id=_load_places(c)[slug])
        elif kind == "cat":
            slug, _, query = rest.partition(":")
            _load_places(c)
            params.update(query=query, discover_category_api_id=_categories[slug])
        elif kind == "city":
            city, params["query"] = rest, "hackathon " + rest
        else:
            params["query"] = rest if kind == "global" else "online " + rest
        data = _get(c, params)
    if not isinstance(data.get("entries"), list):
        raise RuntimeError("Luma discovery response changed: missing entries")
    if len(data["entries"]) >= PAGE:
        log.info("saturated scope %s: %d entries (more may exist)", scope, len(data["entries"]))
    return list(relevant_events(data["entries"], city).values())


def collect() -> list[Event]:
    events: dict[str, Event] = {}
    for scope in scopes("full"):
        for event in collect_scope(scope):
            events[event.url] = event
    return sorted(events.values(), key=lambda e: e.start.isoformat() if e.start else "9999")
