"""Public Luma JSON: ranked keyword discovery plus cursor-paginated city/category feeds,
calendar watchlist and hosts' public upcoming events. No login or browser.

Website JS (2026-11-23): search uses get-paginated-events once; the no-query city feed
uses pagination_cursor / pagination_limit and next_cursor / has_more. City feeds are
curated, NOT every event in a city. Calendar and host listings recover unindexed events.
RANKED_SEARCH remains necessary. HF_LUMA_LEARN=1 persists observed calendar evidence.
Sitemaps are not crawled: sitemap.luma.com/robots.txt returns 403.
"""
import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx

from hackfinder.models import Event
from ._signals_util import geo, names, reward
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
RELEVANT = re.compile(r"hack|buildathon|datathon|makeathon|ideathon|game[ -]jam|codefest|build day|build night|"
                      r"ハッカソン|해커톤|hackaton|hakaton", re.I)
log = logging.getLogger(__name__)
_places: dict[str, str] = {}
_categories: dict[str, str] = {}
_calendars: dict[str, dict] = {}  # api_id -> {"name", "hits"}: calendars that posted a relevant event this run
_hosts: dict[str, dict] = {}
_entries: dict[str, dict] = {}
_blocked = 0
_checked = False


def _text(entry, raw):
    return raw.get("description") or raw.get("description_md") or " ".join(
        x.get("text", "") for x in walk(entry.get("description_mirror") or raw.get("description_mirror"))
        if x.get("type") == "text")


def _signals(entry, raw, hosts, calendar):
    """Quality evidence for the Hackfinder Score; only what the API really returns. Discover entries
    carry no ticket capacity (only spots_remaining), so there is no "capacity"."""
    ticket = entry.get("ticket_info") or {}
    price = ticket.get("price") or {}
    cents = price.get("cents") if isinstance(price.get("cents"), (int, float)) else 0
    paid = ticket.get("is_free") is False or cents > 0
    guests = entry.get("guest_count")
    text = _text(entry, raw)
    signals = {
        "guests": guests if isinstance(guests, int) and guests > 0 and not raw.get("hide_rsvp") else None,
        "hosts": [x["name"] for x in entry.get("hosts", []) if x.get("name")] or None,
        "calendar_id": calendar.get("api_id"),
        "calendar_name": calendar.get("name"),
        "paid_entry": paid if ticket else None,
        "entry_fee": f"{cents / 100:.2f} {str(price.get('currency') or '').upper()}".strip() if cents > 0 else None,
        "featured": True if entry.get("featured_guests") else None,
        "text": " ".join(str(text or "").split())[:3000] or None,
        "registrations": guests if isinstance(guests, int) and not raw.get("hide_rsvp") else None,
        "host_ids": [x["api_id"] for x in entry.get("hosts", []) if x.get("api_id")] or None,
        "sponsors": names(entry.get("sponsors")) or None,
        "themes": names(entry.get("categories")) or None,
    }
    # Only explicit prize sentences: entry fees, credits and API budgets are not cash prizes.
    for sentence in re.split(r"[\n.!?]", text):
        if re.search(r"\b(?:cash prize|prize pool|prizes?)\b", sentence, re.I) and not re.search(r"\b(?:credits?|vouchers?)\b", sentence, re.I):
            signals.update(reward(sentence))
            if signals.get("prize_amount") is not None:
                break
    info = raw.get("geo_address_info") or {}
    coordinate = raw.get("coordinate") or {}
    signals.update(geo(coordinate.get("latitude", raw.get("geo_latitude")), coordinate.get("longitude", raw.get("geo_longitude")),
                       info.get("full_address") or ", ".join(str(x) for x in (info.get("address"), info.get("city")) if x)))
    return {k: v for k, v in signals.items() if v is not None}


def _event(entry):
    raw = entry.get("event") or {}
    if raw.get("cancelled_at") or raw.get("canceled_at") or raw.get("status") in ("cancelled", "canceled"):
        return None
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
    signals = _signals(entry, raw, hosts, calendar)
    prize = f"{signals['prize_amount']:g} {signals['prize_currency']}" if "prize_amount" in signals else None
    return Event(signals=signals, prize=prize,
                 source="luma", source_id=raw.get("api_id") or entry.get("api_id"),
                 title=title, url=urljoin("https://luma.com/", raw["url"]),
                 description=plain(_text(entry, raw)),
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
        params = dict(params)
        data = polite_json(c, API + params.pop("_path", "/discover/get-paginated-events"), params=params)
        _blocked = 0
        return data
    except RuntimeError as exc:
        _blocked += str(exc).startswith("blocked")
        raise


def _pages(c, params):
    """The website's pagination_cursor/next_cursor contract, with stalled-page protection."""
    seen, cursors = set(), set()
    for _ in range(MAX_PAGES):
        data = _get(c, params)
        rows = data.get("entries")
        if not isinstance(rows, list):
            raise RuntimeError("Luma listing response changed: missing entries")
        fresh = []
        for row in rows:
            raw = row.get("event") or {}
            key = raw.get("api_id") or row.get("api_id") or raw.get("url")
            if key and key not in seen:
                seen.add(key)
                fresh.append(row)
        if not fresh:
            break
        yield fresh
        cursor = data.get("next_cursor") or data.get("pagination_cursor")
        if data.get("has_more") is False or not cursor:
            break
        if cursor in cursors:
            log.warning("Luma cursor stalled for %s", params)
            break
        cursors.add(cursor)
        params = {**params, "pagination_cursor": cursor}
    else:
        warn_limit(__name__, str(params))


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
    _calendars.clear()
    _hosts.clear()
    _entries.clear()
    online = [f"{kind}:{q}" for q in QUERIES for kind in ("global", "online")]
    if pass_name != "full":
        return [s for s in online if s.endswith(":hackathon")] + [f"place:{p}:hackathon" for p in QUICK_PLACES]
    with client(timeout=6) as c:
        places = _load_places(c)
    return (online + [f"global:{q}" for q in MORE_QUERIES] + [f"online:{q}" for q in ONLINE_MORE]
            + [f"place:{p}:{q}" for p in places for q in (QUERIES if p in BIG_PLACES else PLACE_QUERIES)]
            + [f"city:{city}" for city in CITY_QUERIES]
            + [f"cat:{slug}:{q}" for slug in CATEGORIES if slug in _categories for q in CATEGORY_QUERIES]
            + [f"feed:{p}" for p in places]
            + [f"category:{slug}" for slug in CATEGORIES if slug in _categories]
            + ["calendars", "hosts", "details"])


def relevant_events(entries, city=None) -> dict[str, Event]:
    """Entries -> upcoming relevant events by api_id. Search is fuzzy, so the keyword filter keeps the
    raw evidence for the classifier. Calendars that posted one are remembered for the calendars scope."""
    events = {}
    for entry in entries:
        raw = entry.get("event") or {}
        if not RELEVANT.search(raw.get("name", "") + " " + _text(entry, raw)):
            continue
        if city and not _in_city(entry, city):
            continue
        event = _event(entry)
        if event and event.source_id:
            events[event.source_id] = event
            _entries[event.source_id] = entry
            calendar = entry.get("calendar") or {"api_id": raw.get("calendar_api_id")}
            _remember_calendar(calendar, event.source_id)
            for host in entry.get("hosts") or []:
                if host.get("api_id"):
                    _hosts[host["api_id"]] = host
            if raw.get("user_api_id"):
                _hosts.setdefault(raw["user_api_id"], {"api_id": raw["user_api_id"]})
    return events


def _remember_calendar(calendar, event_id=None):
    api_id = calendar.get("api_id")
    if not api_id:
        return
    seen = _calendars.setdefault(api_id, {"name": calendar.get("name") or "", "hits": 0, "events": set()})
    if calendar.get("name"):
        seen["name"] = calendar["name"]
    if calendar.get("slug"):
        seen["slug"] = calendar["slug"]
    if event_id:
        seen["events"].add(event_id)
        seen["hits"] = len(seen["events"])


def learn_calendars():
    """Opt-in, atomic merge. Repeated search hits don't make a calendar hackathon-heavy."""
    if os.environ.get("HF_LUMA_LEARN") != "1":
        return
    try:
        data = json.loads(CALENDARS_FILE.read_text(encoding="utf-8"))
        rows = {x["api_id"]: x for x in data.get("calendars", [])}
        today = datetime.now(timezone.utc).date().isoformat()
        for api_id, seen in _calendars.items():
            if not seen["hits"] or (api_id not in rows and seen["hits"] < 2):
                continue
            row = rows.setdefault(api_id, {"api_id": api_id})
            row.update(name=seen["name"], last_seen=today)
            if seen.get("slug"):
                row["slug"] = seen["slug"]
        data["calendars"] = list(rows.values())
        # Replace atomically; do not leave an extra tracked file behind.
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CALENDARS_FILE.parent,
                                         prefix=".luma-", suffix=".tmp", delete=False) as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")
        try:
            os.replace(f.name, CALENDARS_FILE)
        finally:
            Path(f.name).unlink(missing_ok=True)
    except (OSError, ValueError):
        log.exception("could not save Luma calendar watchlist")


def _over_budget(started, what):
    """Expansion scopes (calendars/hosts/details) each get HF_LUMA_EXPAND_SECONDS (default 15 min)."""
    if time.monotonic() - started > float(os.environ.get("HF_LUMA_EXPAND_SECONDS", "900")):
        log.warning("luma %s: time budget reached, keeping what was found", what)
        return True
    return False


def _refused(exc, what, strikes):
    """A 403/429 on one calendar/host/event: skip it and cool down; after 3 in a row stop the loop
    (returns None) but keep what was found, instead of failing the whole scope."""
    global _blocked
    if not str(exc).startswith("blocked"):
        raise exc
    _blocked = 0
    if strikes + 1 >= 3:
        log.warning("luma %s: refused 3 times in a row, keeping what was found", what)
        return None
    log.info("luma %s: refused (%s), cooling down", what, exc)
    time.sleep(float(os.environ.get("HF_LUMA_COOLDOWN", "20")))
    return strikes + 1


def _collect_calendars(order=None):
    """No time/event cap; exhaust each calendar, up to the shared 100-page safety limit."""
    order = calendar_order(seed_calendars(), _calendars) if order is None else order
    events = {}
    with client(timeout=10) as c:
        started, strikes = time.monotonic(), 0
        for api_id, name in order:
            if _over_budget(started, 'calendars'):
                break
            try:
                for rows in _pages(c, {"_path": "/calendar/get-items", "calendar_api_id": api_id,
                                       "period": "future", "pagination_limit": PAGE}):
                    events.update(relevant_events(rows))
                strikes = 0
            except RuntimeError as exc:
                if (strikes := _refused(exc, 'calendars', strikes)) is None:
                    break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (400, 404, 410):
                    raise
                log.info("calendar %s (%s) skipped: HTTP %s", api_id, name, exc.response.status_code)
    learn_calendars()
    log.info("calendars: %d crawled, %d relevant upcoming events", len(order), len(events))
    return list(events.values())


def _collect_hosts():
    """One host expansion from discovery/calendars, then their newly seen calendars.
    Don't recursively traverse hosts-of-hosts: that unbounded social graph is not a daily feed.
    """
    events, known = {}, set(seed_calendars()) | set(_calendars)
    hosts = list(_hosts)
    with client(timeout=10) as c:
        started, strikes = time.monotonic(), 0
        for api_id in hosts:
            if _over_budget(started, 'hosts'):
                break
            try:
                for rows in _pages(c, {"_path": "/user/profile/events-hosting", "user_api_id": api_id,
                                       "period": "future", "pagination_limit": PAGE}):
                    events.update(relevant_events(rows))
                strikes = 0
            except RuntimeError as exc:
                if (strikes := _refused(exc, 'hosts', strikes)) is None:
                    break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (400, 404, 410):
                    raise
                log.info("host %s skipped: HTTP %s", api_id, exc.response.status_code)
    extra = [(k, v["name"]) for k, v in _calendars.items() if k not in known]
    events.update({e.source_id: e for e in _collect_calendars(extra)})
    learn_calendars()
    log.info("hosts: %d crawled, %d relevant upcoming events", len(hosts), len(events))
    return list(events.values())


def _collect_details():
    """One detail per unique event, after expansion; quick discovery makes no detail requests."""
    events = {}
    with client(timeout=10) as c:
        started, strikes = time.monotonic(), 0
        for api_id, entry in list(_entries.items()):
            if _over_budget(started, 'details'):
                break
            if not api_id.startswith("evt-"):
                continue  # External calendar entries already carry their original registration URL.
            try:
                detail = _get(c, {"_path": "/event/get", "event_api_id": api_id})
                strikes = 0
            except RuntimeError as exc:
                if (strikes := _refused(exc, 'details', strikes)) is None:
                    break
                continue
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (404, 410):
                    raise
                continue
            merged = {**entry, **detail, "event": {**entry["event"], **detail.get("event", {})}}
            events.update(relevant_events([merged]))
            for calendar in detail.get("collaborating_calendars") or []:
                _remember_calendar(calendar.get("calendar", calendar), api_id)
    learn_calendars()
    return list(events.values())


def collect_scope(scope: str) -> list[Event]:
    """Search stays small; feeds, calendars and hosts follow actual cursor pagination."""
    if scope == "calendars":
        return _collect_calendars()
    if scope == "hosts":
        return _collect_hosts()
    if scope == "details":
        return _collect_details()
    kind, _, rest = scope.partition(":")
    params = {"pagination_limit": PAGE}
    city = None
    with client(timeout=6) as c:
        if kind in ("feed", "category"):
            _load_places(c)
            key = "discover_place_api_id" if kind == "feed" else "discover_category_api_id"
            params[key] = (_places if kind == "feed" else _categories)[rest]
            if kind == "feed":
                featured = _get(c, {"_path": "/discover/get-calendars", key: params[key]})
            else:
                featured = _get(c, {"_path": "/url", "url": rest}).get("data", {})
            for node in walk(featured):
                if str(node.get("api_id", "")).startswith("cal-"):
                    _remember_calendar(node)
        elif kind == "place":
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
        events = {}
        for rows in _pages(c, params):
            if params.get("query") and len(rows) >= PAGE:
                log.info("saturated scope %s: %d entries (more may exist)", scope, len(rows))
            events.update(relevant_events(rows, city))
    return list(events.values())


def collect() -> list[Event]:
    events: dict[str, Event] = {}
    for scope in scopes(os.environ.get("HF_LUMA_PASS", "full")):
        for event in collect_scope(scope):
            events[event.source_id] = event
    return sorted(events.values(), key=lambda e: e.start.isoformat() if e.start else "9999")
