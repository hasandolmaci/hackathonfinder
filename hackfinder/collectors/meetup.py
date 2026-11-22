"""Meetup: keyword search for "hackathon", scraped with SeleniumBase CDP + Playwright connect_over_cdp.

Scoped collector: "global", "online", then batches of searches ("locs:<item>|<item>|..."), where
an item is a location in Meetup's format cc--[region--]City ("loc:<param>" alone also works) or
"<keyword>@<location>" for a second keyword in a big city. A batch shares ONE Chrome session.
Each search scrolls its results until two scrolls in a row bring no new event IDs (at most 30).

Measured URL parameters (2026-11-22; all work, none reveals more hackathons than keywords + location):
distance=hundredMiles (same results as the default radius), eventType=online|inPerson (a subset),
categoryId=546 (technology; a subset), sortField=DATETIME (shows fewer results), customStartDate /
customEndDate (works, no gain). /topics/hackathon/ pages return no events in the page data.

Sources of data on each search page:
- the server-rendered Apollo cache in __NEXT_DATA__ (first ~20 results), and
- the GraphQL JSON responses the page fetches while we scroll (more results).
Meetup is a mixed platform, so kind stays "unknown" and classify.py decides.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

from hackfinder.browser import cdp_page
from hackfinder.models import Event

SOURCE = {"id": "meetup", "name": "Meetup",
          "url": "https://www.meetup.com/find/?keywords=hackathon&source=EVENTS",
          "method": "scrape", "default_kind": "mixed"}
RANKED_SEARCH = True  # keyword search + scrolling: absence never proves an event is gone

BASE = "https://www.meetup.com/find/?keywords=hackathon&source=EVENTS"
# Meetup location format: cc--[region--]City. Every entry was checked against the city Meetup actually
# resolves it to (a wrong guess silently falls back to the IP-based location): Munich needs "München",
# Milan "Milano", Gothenburg "Göteborg"; Rome has no working form and is left out.
LOCATIONS = [
    # North America
    "us--ca--San Francisco", "us--ny--New York", "us--il--Chicago", "us--wa--Seattle", "us--tx--Austin",
    "us--ma--Boston", "us--ca--Los Angeles", "us--ca--San Jose",
    "us--co--Denver", "us--dc--Washington", "us--ga--Atlanta", "us--fl--Miami", "us--pa--Philadelphia",
    "us--mn--Minneapolis", "us--az--Phoenix", "us--or--Portland", "us--ut--Salt Lake City",
    "us--mi--Ann Arbor", "us--pa--Pittsburgh", "us--tx--Dallas", "us--tx--Houston", "us--oh--Columbus",
    "ca--on--Toronto", "ca--bc--Vancouver",
    "mx--Mexico City",
    # Europe
    "gb--17--London", "de--Berlin", "nl--Amsterdam", "fr--Paris", "de--München", "es--Barcelona", "es--Madrid",
    "se--Stockholm", "pl--Warsaw", "pl--Krakow", "ie--Dublin", "pt--Lisbon", "it--Milano", "ch--Zurich",
    "at--Vienna", "be--Brussels", "dk--Copenhagen", "no--Oslo", "fi--Helsinki", "cz--Prague",
    "ro--Bucharest", "ua--Kyiv", "de--Hamburg", "de--Frankfurt", "fr--Lyon", "gb--Manchester",
    "nl--Eindhoven", "nl--Rotterdam", "lt--Vilnius", "ee--Tallinn", "rs--Belgrade",
    "hr--Zagreb", "se--Göteborg", "tr--Istanbul",
    # Netherlands (each resolves to its own city, checked by the page heading "events near <city>, NL")
    "nl--Utrecht", "nl--The Hague", "nl--Delft", "nl--Leiden", "nl--Groningen", "nl--Nijmegen", "nl--Enschede",
    "nl--Maastricht", "nl--Tilburg", "nl--Breda", "nl--Haarlem", "nl--Arnhem", "nl--Amersfoort", "nl--'s-Hertogenbosch",
    # Middle East and Africa
    "ae--Dubai", "ae--Abu Dhabi", "il--Tel Aviv-Yafo", "ng--Lagos", "ng--Abuja", "ke--Nairobi",
    "za--Cape Town", "za--Johannesburg", "eg--Cairo", "gh--Accra", "rw--Kigali", "ug--Kampala",
    # Asia and Oceania
    "in--Bangalore", "in--Mumbai", "in--New Delhi", "in--Hyderabad", "in--Pune", "in--Chennai", "in--Kolkata",
    "sg--Singapore", "jp--Tokyo", "jp--Osaka", "kr--Seoul", "hk--Hong Kong", "tw--Taipei",
    "my--Kuala Lumpur", "id--Jakarta", "ph--Manila", "vn--Ho Chi Minh City", "lk--Colombo",
    "pk--Karachi", "au--Sydney", "au--Brisbane", "nz--Auckland",
    # South America
    "br--Sao Paulo", "br--Rio de Janeiro", "ar--Buenos Aires", "co--Bogota", "cl--Santiago", "pe--Lima",
    "uy--Montevideo",
]
# Second keyword for the biggest tech scenes, where "hackathon" alone ranks other events first.
EXTRA_KEYWORDS = {"hack night": ["us--ca--San Francisco", "us--ny--New York", "gb--17--London", "de--Berlin",
                                 "us--wa--Seattle"]}
BATCH = 8  # Locations per scope: they share one Chrome session instead of starting Chrome per location.
SCROLLS = 30  # Safety limit per scope.
SCROLL_WAIT = 1000  # ms between scrolls.
IDLE_SCROLLS = 2  # Stop after this many scrolls in a row with no new event IDs.
# Keyword pre-filter (DECISIONS.md tier 2): Meetup also returns unrelated "recommended" events.
# A bare "jam" is not matched: on Meetup it finds music and improv jam sessions, not game jams.
HACK_RE = re.compile(r"hack|game ?jam|buildathon|build (day|night|weekend)|datathon|makeathon|ideathon|codefest|"
                     r"\bctf\b|capture the flag|hackaton|hakaton|хакатон|ハッカソン|해커톤|黑客松", re.I)
log = logging.getLogger(__name__)
FORMATS = {"PHYSICAL": "in-person", "ONLINE": "online", "HYBRID": "hybrid"}


def _walk(value):
    """Yield every dict inside a JSON value."""
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


def _resolve(value, cache):
    if isinstance(value, dict) and "__ref" in value:
        return cache.get(value["__ref"], {})
    return value or {}


def _signals(raw: dict, group: dict, desc: str, rsvps) -> dict:
    """Quality evidence for the Hackfinder Score; only what the page really returns."""
    hosts = [(((e.get("node") or {}).get("user") or {}).get("name"))
             for e in ((raw.get("rsvps") or {}).get("edges") or []) if (e.get("node") or {}).get("isHost")]
    fee = raw.get("feeSettings") or {}
    amount = fee.get("amount") if isinstance(fee.get("amount"), (int, float)) else None
    capacity = raw.get("maxTickets")
    signals = {
        "rsvps": rsvps if isinstance(rsvps, int) and rsvps > 0 else None,
        "hosts": [h for h in hosts if h] or None,
        "calendar_name": group.get("name"),
        "paid_entry": bool(amount and amount > 0),
        "entry_fee": f"{amount:g} {fee.get('currency') or ''}".strip() if amount and amount > 0 else None,
        "capacity": capacity if isinstance(capacity, int) and capacity > 0 else None,
        "text": desc[:3000] or None,
    }
    return {k: v for k, v in signals.items() if v is not None}


def _event(raw: dict, cache: dict) -> Event | None:
    url, title, when = raw.get("eventUrl"), raw.get("title"), raw.get("dateTime")
    if not (url and title and when):
        return None
    try:
        start = datetime.fromisoformat(when).astimezone(timezone.utc)
    except ValueError:
        return None
    end = None
    if raw.get("endTime"):
        try:
            end = datetime.fromisoformat(raw["endTime"]).astimezone(timezone.utc)
        except ValueError:
            pass
    if (end or start) < datetime.now(timezone.utc):
        return None
    venue = raw.get("venue") or {}
    fmt = FORMATS.get(raw.get("eventType") or "", "unknown")
    city, country = venue.get("city"), (venue.get("country") or "").upper() or None
    location = ", ".join(x for x in (city, country) if x) or None
    if fmt == "online" or (venue.get("name") or "").lower() == "online event":
        fmt, location = "online", None
    group = _resolve(raw.get("group"), cache)
    photo = _resolve(raw.get("featuredEventPhoto") or raw.get("displayPhoto"), cache)
    desc = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", raw.get("description") or "")
    desc = re.sub(r"[*_#>]+", "", desc).strip()
    rsvps = (raw.get("rsvps") or {}).get("totalCount")
    return Event(
        signals=_signals(raw, group, desc, rsvps),
        source="meetup", source_id=str(raw.get("id") or ""), url=url.split("?")[0],
        title=title.strip(), description=desc[:500] or None,
        image=photo.get("highResUrl") or photo.get("baseUrl") and f"{photo['baseUrl']}{photo.get('id', '')}/676x380.webp" or None,
        start=start, end=end, format=fmt, location=location, country=country,
        participants=rsvps if isinstance(rsvps, int) else None,
        organizer=group.get("name"),
    )


def parse_payloads(payloads: list) -> list[Event]:
    """Turn Apollo caches / GraphQL responses into Events (pure; testable offline)."""
    cache: dict = {}
    for p in payloads:
        if isinstance(p, dict) and any(":" in k and isinstance(v, dict) and "__typename" in v for k, v in list(p.items())[:50]):
            cache.update(p)  # Apollo normalized cache
    out: dict[str, Event] = {}
    for p in payloads:
        for node in _walk(p):
            if node.get("__typename") == "Event" or ("eventUrl" in node and "dateTime" in node):
                ev = _event(node, cache)
                if ev and ev.url not in out:
                    out[ev.url] = ev
    return list(out.values())


def _apollo_from_html(html: str):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    data = json.loads(m.group(1))
    return data.get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__")


def _ids(payloads: list) -> set:
    return {n.get("id") or n["eventUrl"] for p in payloads for n in _walk(p)
            if n.get("__typename") == "Event" or ("eventUrl" in n and "dateTime" in n)}


def searches() -> list[str]:
    """Every search item of the full run, in order: plain locations first, then the second keywords."""
    return ([f"loc:{loc}" for loc in LOCATIONS]
            + [f"kw:{kw}@{loc}" for kw, locs in EXTRA_KEYWORDS.items() for loc in locs])


def scopes(pass_name: str) -> list[str]:
    """Meetup only runs in the full pass, so every pass gets every search."""
    items = searches()
    return ["global", "online"] + ["locs:" + "|".join(items[i:i + BATCH]) for i in range(0, len(items), BATCH)]


def _url(item: str) -> str:
    kind, _, rest = item.partition(":")
    if kind == "kw":
        keyword, _, loc = rest.partition("@")
        return BASE.replace("keywords=hackathon", "keywords=" + quote(keyword)) + "&location=" + quote(loc)
    return BASE + ("&eventType=online" if kind == "online" else "&location=" + quote(rest) if kind == "loc" else "")


def _scan(page, scope: str, payloads: list) -> None:
    """Load one search and scroll until IDLE_SCROLLS scrolls in a row add no new event IDs."""
    url = _url(scope)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    html = page.content()
    if re.search(r"captcha|are you a robot|access denied", html[:20000], re.I) and "__NEXT_DATA__" not in html:
        raise RuntimeError(f"blocked on {url}")
    apollo = _apollo_from_html(html)
    if apollo:
        payloads.append(apollo)
    seen, idle = _ids(payloads), 0
    for _ in range(SCROLLS):
        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(SCROLL_WAIT)
        now = _ids(payloads)
        idle = 0 if now - seen else idle + 1
        seen = now
        if idle >= IDLE_SCROLLS:
            break
    else:
        log.warning("hit the %d-scroll safety limit for scope %s", SCROLLS, scope)


def _items(scope: str) -> list[str]:
    kind, _, rest = scope.partition(":")
    return rest.split("|") if kind == "locs" else [scope]


def _run(scope_list: list[str]) -> list[Event]:
    events: dict[str, Event] = {}
    errors: list[str] = []
    with cdp_page() as page:
        payloads: list = []
        def on_response(resp):
            if "/gql" in resp.url and resp.request.method == "POST":
                try:
                    payloads.append(resp.json())
                except Exception:
                    pass
        page.on("response", on_response)
        blocked = 0
        for scope in [item for s in scope_list for item in _items(s)]:
            payloads.clear()
            started, before = time.monotonic(), len(events)
            try:
                _scan(page, scope, payloads)
                blocked = 0
            except Exception as exc:  # one bad search must not lose the rest
                errors.append(f"{scope}: {type(exc).__name__}")
                blocked = blocked + 1 if str(exc).startswith("blocked") else 0
            for e in parse_payloads(payloads):
                if HACK_RE.search(f"{e.title} {e.description or ''}"):
                    events.setdefault(e.url, e)
            log.info("meetup %s: %d new relevant events in %.0fs", scope, len(events) - before, time.monotonic() - started)
            if blocked >= 2:
                errors.append("stopped after repeated blocks")
                break
    if not events and errors:
        raise RuntimeError("; ".join(errors)[:300])
    return list(events.values())


def collect_scope(scope: str) -> list[Event]:
    return _run([scope])


def collect() -> list[Event]:
    return _run(scopes("full"))
