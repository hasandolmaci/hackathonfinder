"""Eventbrite: keyword search for "hackathon" in online + major tech-city scopes.

Scoped collector: scope "online" or "city:<country>--<city>" (Eventbrite's /d/ slug).
Plain httpx is enough: each search page embeds `window.__SERVER_DATA__` (20 results per
page; ?page=N), plus schema.org JSON-LD with venue address and image. Results are
ranked by relevance and trail off into generic tech/networking events, so a scope stops
after IDLE_PAGES pages in a row with no hackathon-keyword match, at the last page, or at
the safety limit. Eventbrite is a mixed platform: kind stays "unknown" and classify.py decides.
"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from hackfinder.models import Event
from ._signals_util import source_signals
from ._vertical_util import MAX_PAGES, client, plain, robots, warn_limit

SOURCE = {"id": "eventbrite", "name": "Eventbrite",
          "url": "https://www.eventbrite.com/d/online/hackathon/",
          "method": "api", "default_kind": "mixed"}
RANKED_SEARCH = True  # ranked keyword search: absence never proves an event is gone

BASE = "https://www.eventbrite.com/d/{}/hackathon/"
CITIES = [
    "ca--san-francisco", "ny--new-york", "ca--los-angeles", "wa--seattle", "tx--austin", "ma--boston",
    "il--chicago", "dc--washington", "ga--atlanta", "co--denver", "fl--miami", "tx--dallas",
    "canada--toronto", "canada--vancouver", "united-kingdom--london", "united-kingdom--manchester",
    "ireland--dublin", "germany--berlin", "germany--munich", "france--paris", "spain--barcelona",
    "spain--madrid", "netherlands--amsterdam", "sweden--stockholm", "poland--warsaw",
    "portugal--lisbon", "switzerland--zurich", "turkey--istanbul", "united-arab-emirates--dubai",
    "israel--tel-aviv-yafo", "india--bangalore", "india--mumbai", "india--delhi", "india--hyderabad",
    "singapore--singapore", "japan--tokyo", "south-korea--seoul", "australia--sydney",
    "australia--melbourne", "brazil--sao-paulo", "mexico--mexico-city", "nigeria--lagos",
    "kenya--nairobi", "south-africa--cape-town",
    # Netherlands: Eventbrite ranks a country-wide search per slug (small cities have no page of their own and
    # fall back to the country), so the country scope plus each city ranking surfaces different Dutch events.
    "netherlands", "netherlands--rotterdam", "netherlands--utrecht", "netherlands--eindhoven",
    "netherlands--the-hague", "netherlands--delft", "netherlands--groningen", "netherlands--leiden",
    "netherlands--nijmegen", "netherlands--enschede", "netherlands--maastricht", "netherlands--tilburg",
    "netherlands--breda", "netherlands--haarlem", "netherlands--arnhem",
]
IDLE_PAGES = 2  # Stop after this many pages in a row without a hackathon-keyword match.
# Keyword pre-filter (DECISIONS.md tier 2), as in meetup.py; "life hack" style tips are noise.
HACK_RE = re.compile(r"hack|game ?jam|\bjam\b|buildathon|build (day|night|weekend)|datathon|makeathon|ideathon|\bctf\b|capture the flag|hackaton|hakaton|ハッカソン|해커톤|黑客松", re.I)
NOISE_RE = re.compile(r"life ?hack|growth ?hack|biohack", re.I)
SERVER_DATA = re.compile(r"window\.__SERVER_DATA__\s*=\s*")


def _stamp(day, clock, zone):
    """Local date + HH:MM in the event's IANA zone -> UTC (date-only -> midnight UTC)."""
    try:
        naive = datetime.strptime(f"{day} {clock or '00:00'}", "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return None
    try:
        return naive.replace(tzinfo=ZoneInfo(zone) if clock else timezone.utc).astimezone(timezone.utc)
    except Exception:
        return naive.replace(tzinfo=timezone.utc)


def _place(item):
    """(location, country, is_virtual) from a JSON-LD Event item."""
    loc = item.get("location") or {}
    if loc.get("@type") == "VirtualLocation" or "Online" in str(item.get("eventAttendanceMode", "")):
        return None, None, True
    addr = loc.get("address") or {}
    country = addr.get("addressCountry") if isinstance(addr, dict) else None
    city = addr.get("addressLocality") if isinstance(addr, dict) else None
    return ", ".join(x for x in (loc.get("name"), city, country) if x) or None, country, False


def parse(html: str) -> tuple[list[Event], int, int]:
    """One search page -> (hackathon-keyword events, page_count, results on the page). Pure."""
    m = SERVER_DATA.search(html)
    if not m:
        raise RuntimeError("blocked: Eventbrite page has no __SERVER_DATA__")
    data = json.JSONDecoder().raw_decode(html[m.end():])[0]
    ld = {}
    for block in data.get("jsonld") or []:
        for row in block.get("itemListElement", []) if isinstance(block, dict) else []:
            item = row.get("item") or {}
            if item.get("url"):
                ld[item["url"].split("?")[0]] = item
    results = ((data.get("search_data") or {}).get("events") or {}).get("results") or []
    now, events = datetime.now(timezone.utc), []
    for r in results:
        title, url = (r.get("name") or "").strip(), (r.get("url") or "").split("?")[0]
        summary = plain(r.get("summary"))
        if not title or not url or r.get("is_cancelled"):
            continue
        if not HACK_RE.search(f"{title} {summary or ''}") or NOISE_RE.search(title):
            continue
        zone = r.get("timezone") or "UTC"
        start = _stamp(r.get("start_date"), r.get("start_time"), zone)
        end = _stamp(r.get("end_date") or r.get("start_date"), r.get("end_time"), zone)
        if (end or start) is None or (end or start) < now:
            continue
        item = ld.get(url, {})
        place, country, virtual = _place(item) if item else (None, None, False)
        online = bool(r.get("is_online_event")) or virtual
        if not online and not place:  # fall back to the result's own place hierarchy
            names = {x.get("type"): x.get("name") for x in r.get("locations") or []}
            place = ", ".join(x for x in (names.get("locality"), names.get("country")) if x) or None
            country = names.get("country")
        tags = [t["display_name"] for t in r.get("tags") or []
                if t.get("prefix") in ("EventbriteCategory", "EventbriteSubCategory", "OrganizerTag") and t.get("display_name")]
        image = item.get("image")
        events.append(Event(
            source="eventbrite", signals=source_signals("eventbrite", r, item), source_id=str(r.get("eid") or r.get("id") or ""), url=url, title=title,
            description=plain(item.get("description")) or summary, image=image if isinstance(image, str) else None,
            start=start, end=end, format="online" if online else "in-person" if place else "unknown",
            location=None if online else place, country=None if online else country, tags=tags[:8]))
    return events, int(data.get("page_count") or 1), len(results)


def scopes(pass_name: str) -> list[str]:
    """Ranked search: the full pass gets every scope; quick/browser passes take the biggest hubs
    (through Chrome a scope takes ~25 s, and the browser pass gives a source 15 minutes)."""
    every = ["online"] + [f"city:{c}" for c in CITIES]
    return {"quick": every[:8], "browser": every[:16]}.get(pass_name, every)


_use_browser = False  # set once plain HTTP is refused (datacenter IPs such as GitHub Actions get 405)


def _pages(fetch, url, scope):
    """Walk ?page=N with `fetch(page_url) -> (status, html)` until exhausted."""
    events, idle = {}, 0
    for page in range(1, MAX_PAGES + 1):
        if page > 1:
            time.sleep(1 + random.uniform(0, 0.5))
        status, html = fetch(f"{url}?page={page}" if page > 1 else url)
        if status in (401, 403, 405, 429):
            raise PermissionError(f"blocked: HTTP {status} from {url}")
        if status == 404 and page == 1:
            raise RuntimeError(f"Eventbrite has no search page for scope {scope}")
        if status >= 400:
            raise RuntimeError(f"HTTP {status} from {url}")
        found, last, total = parse(html)
        events.update({e.url: e for e in found})
        idle = 0 if found else idle + 1
        if not total or page >= last or idle >= IDLE_PAGES:
            break
    else:
        warn_limit(__name__, scope)
    return list(events.values())


def _browser_pages(url, scope):
    """Same walk through hackfinder.browser.cdp_page, for when plain HTTP is refused."""
    from hackfinder.browser import cdp_page
    with cdp_page() as page:
        def fetch(page_url):
            resp = page.goto(page_url, wait_until="domcontentloaded")
            html = page.content()
            if not SERVER_DATA.search(html):  # give an interstitial a moment to clear by itself
                page.wait_for_timeout(5000)
                html = page.content()
            status = resp.status if resp else 200
            return (200 if SERVER_DATA.search(html) else status), html
        return _pages(fetch, url, scope)


def collect_scope(scope: str) -> list[Event]:
    global _use_browser
    kind, _, slug = scope.partition(":")
    url = BASE.format("online" if kind == "online" else slug)
    if not _use_browser:
        try:
            with client(timeout=20) as c:
                robots(c, url)
                def fetch(page_url):
                    r = c.get(page_url, headers={"Accept": "text/html"})
                    return r.status_code, r.text
                return _pages(fetch, url, scope)
        except PermissionError:
            _use_browser = True  # plain HTTP refused: use the real browser for the rest of the run
    try:
        return _browser_pages(url, scope)
    except PermissionError as exc:
        raise RuntimeError(str(exc)) from None


def collect() -> list[Event]:
    events, errors = {}, []
    for scope in scopes("full"):
        try:
            events.update({e.url: e for e in collect_scope(scope)})
        except Exception as exc:  # one bad scope must not lose the rest
            errors.append(f"{scope}: {type(exc).__name__}: {exc}")
    if not events and errors:
        raise RuntimeError("; ".join(errors)[:300])
    return list(events.values())
