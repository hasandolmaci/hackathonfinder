"""Public discovery JSON. Undocumented website endpoint; no login or key.

Scoped collector. Search returns at most 50 entries per request and ignores
pagination, so coverage comes from many small scopes (query x Luma place, plus
"hackathon <city>" for cities without a place). A scope that returns exactly 50
is saturated and logged. Explicit place IDs avoid the default feed's IP-based
location bias.
"""
import logging
import re
import unicodedata
from urllib.parse import urljoin

from hackfinder.models import Event
from ._vertical_util import client, dt, plain, polite_json, robots, upcoming, walk

SOURCE = {"id": "luma", "name": "Luma", "url": "https://luma.com/discover",
          "method": "api", "default_kind": "mixed"}
RANKED_SEARCH = True  # 50-result ranked searches: absence never proves an event is gone
API = "https://api.lu.ma"
PAGE = 50
QUERIES = ["hackathon", "hack", "buildathon", "datathon", "game jam", "ideathon"]
QUICK_PLACES = ["sf", "nyc", "london", "berlin", "amsterdam", "paris", "bengaluru", "singapore"]
# Cities without a Luma place (and a few extra); searched as "hackathon <city>".
CITY_QUERIES = [
    "Utrecht", "Eindhoven", "Rotterdam", "The Hague", "Delft", "Leiden", "Groningen", "Antwerp", "Ghent",
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
_blocked = 0
_checked = False


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
    return Event(source="luma", source_id=raw.get("api_id") or entry.get("api_id"),
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


def _in_city(entry, city):
    geo = (entry.get("event") or {}).get("geo_address_info") or {}
    cities = [geo.get("city"), geo.get("full_address")]
    cities += [x.get("city") for x in (geo.get("localized") or {}).values()]
    return any(_fold(city) in _fold(x) for x in cities if x)


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
    return _places


def scopes(pass_name: str) -> list[str]:
    online = [f"{kind}:{q}" for q in QUERIES for kind in ("global", "online")]
    if pass_name != "full":
        return [s for s in online if s.endswith(":hackathon")] + [f"place:{p}:hackathon" for p in QUICK_PLACES]
    with client(timeout=6) as c:
        places = _load_places(c)
    return (online + [f"place:{p}:{q}" for p in places for q in QUERIES]
            + [f"city:{city}" for city in CITY_QUERIES])


def collect_scope(scope: str) -> list[Event]:
    """One request: Luma caps a response at 50 entries and ignores pagination."""
    kind, _, rest = scope.partition(":")
    params = {"pagination_limit": PAGE}
    city = None
    with client(timeout=6) as c:
        if kind == "place":
            slug, _, query = rest.partition(":")
            params.update(query=query, discover_place_api_id=_load_places(c)[slug])
        elif kind == "city":
            city, params["query"] = rest, "hackathon " + rest
        else:
            params["query"] = rest if kind == "global" else "online " + rest
        data = _get(c, params)
    if not isinstance(data.get("entries"), list):
        raise RuntimeError("Luma discovery response changed: missing entries")
    if len(data["entries"]) >= PAGE:
        log.info("saturated scope %s: %d entries (more may exist)", scope, len(data["entries"]))
    events = {}
    for entry in data["entries"]:
        raw = entry.get("event") or {}
        # Search is fuzzy. Keep relevant raw evidence for the classifier.
        if not RELEVANT.search(raw.get("name", "") + " " + (raw.get("description") or "")):
            continue
        if city and not _in_city(entry, city):
            continue
        event = _event(entry)
        if event and event.source_id:
            events[event.source_id] = event
    return list(events.values())


def collect() -> list[Event]:
    events: dict[str, Event] = {}
    for scope in scopes("full"):
        for event in collect_scope(scope):
            events[event.url] = event
    return sorted(events.values(), key=lambda e: e.start.isoformat() if e.start else "9999")
