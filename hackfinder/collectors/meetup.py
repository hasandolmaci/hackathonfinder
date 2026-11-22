"""Meetup: keyword search for "hackathon", scraped with SeleniumBase CDP + Playwright connect_over_cdp.

Scoped collector: one scope per search location ("global", "online", or "loc:<param>",
where <param> is Meetup's location format cc--[region--]City). Each scope scrolls its
results until two scrolls in a row bring no new event IDs (at most 30 scrolls).

Sources of data on each search page:
- the server-rendered Apollo cache in __NEXT_DATA__ (first ~20 results), and
- the GraphQL JSON responses the page fetches while we scroll (more results).
Meetup is a mixed platform, so kind stays "unknown" and classify.py decides.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

from hackfinder.browser import cdp_page
from hackfinder.models import Event

SOURCE = {"id": "meetup", "name": "Meetup",
          "url": "https://www.meetup.com/find/?keywords=hackathon&source=EVENTS",
          "method": "scrape", "default_kind": "mixed"}
RANKED_SEARCH = True  # keyword search + scrolling: absence never proves an event is gone

BASE = "https://www.meetup.com/find/?keywords=hackathon&source=EVENTS"
LOCATIONS = [
    "us--ca--San Francisco", "us--ny--New York", "gb--17--London", "de--Berlin", "in--Bangalore",
    "nl--Amsterdam", "ca--on--Toronto", "us--il--Chicago", "us--wa--Seattle", "us--tx--Austin",
    "us--ma--Boston", "us--ca--Los Angeles", "fr--Paris", "de--Munich", "es--Barcelona",
    "se--Stockholm", "pl--Warsaw", "tr--Istanbul", "ae--Dubai", "il--Tel Aviv-Yafo", "sg--Singapore",
    "au--Sydney", "jp--Tokyo", "br--Sao Paulo", "mx--Mexico City", "ng--Lagos", "ke--Nairobi",
]
SCROLLS = 30  # Safety limit per scope.
IDLE_SCROLLS = 2  # Stop after this many scrolls in a row with no new event IDs.
# Keyword pre-filter (DECISIONS.md tier 2): Meetup also returns unrelated "recommended" events.
HACK_RE = re.compile(r"hack|game ?jam|\bjam\b|buildathon|build (day|night|weekend)|datathon|makeathon|ideathon|\bctf\b|capture the flag|hackaton|hakaton|ハッカソン|해커톤|黑客松", re.I)
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


def scopes(pass_name: str) -> list[str]:
    """Meetup only runs in the full pass, so every pass gets every location."""
    return ["global", "online"] + [f"loc:{loc}" for loc in LOCATIONS]


def _scan(page, scope: str, payloads: list) -> None:
    """Load one search and scroll until IDLE_SCROLLS scrolls in a row add no new event IDs."""
    kind, _, loc = scope.partition(":")
    url = BASE + ("&eventType=online" if kind == "online" else "&location=" + quote(loc) if kind == "loc" else "")
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    html = page.content()
    if re.search(r"captcha|are you a robot|access denied", html[:20000], re.I) and "__NEXT_DATA__" not in html:
        raise RuntimeError(f"blocked on {url}")
    apollo = _apollo_from_html(html)
    if apollo:
        payloads.append(apollo)
    seen, idle = _ids(payloads), 0
    for _ in range(SCROLLS):
        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(1200)
        now = _ids(payloads)
        idle = 0 if now - seen else idle + 1
        seen = now
        if idle >= IDLE_SCROLLS:
            break
    else:
        logging.getLogger(__name__).warning("hit the %d-scroll safety limit for scope %s", SCROLLS, scope)


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
        for scope in scope_list:
            payloads.clear()
            try:
                _scan(page, scope, payloads)
            except Exception as exc:  # one bad search must not lose the rest
                errors.append(f"{scope}: {type(exc).__name__}")
            for e in parse_payloads(payloads):
                if HACK_RE.search(f"{e.title} {e.description or ''}"):
                    events.setdefault(e.url, e)
    if not events and errors:
        raise RuntimeError("; ".join(errors)[:300])
    return list(events.values())


def collect_scope(scope: str) -> list[Event]:
    return _run([scope])


def collect() -> list[Event]:
    return _run(scopes("full"))
