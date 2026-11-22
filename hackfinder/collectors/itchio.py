"""Rendered jam calendar and upcoming/in-progress cards; no HTML HTTP scraping."""
import re
from urllib.parse import urljoin

from hackfinder.browser import cdp_page
from hackfinder.models import Event
from ._vertical_util import (MAX_PAGES, browser_worker, check_block, client, dt, embedded,
                             navigate, plain, robots, schema_event, script_objects, upcoming, warn_limit)

SOURCE = {"id": "itchio", "name": "itch.io Jams", "url": "https://itch.io/jams",
          "method": "scrape", "default_kind": "game_jam"}


def collect() -> list[Event]:
    with client() as c:
        for url in [SOURCE["url"], SOURCE["url"] + "/upcoming", SOURCE["url"] + "/in-progress"]:
            robots(c, url)
    return browser_worker("itchio")


def _calendar_event(raw):
    start = dt(raw.get("start_date") or raw.get("startDate") or raw.get("start_at"))
    end = dt(raw.get("end_date") or raw.get("endDate") or raw.get("end_at"))
    url = raw.get("url")
    title = raw.get("title") or raw.get("name")
    if not url or not title or not (start or end) or "/jam/" not in urljoin("https://itch.io", url):
        return None
    if not upcoming(start, end):
        return None
    participants = raw.get("joined") or raw.get("participants")
    if not isinstance(participants, int):
        participants = None
    return Event(source="itchio", source_id=str(raw["id"]) if raw.get("id") else None,
                 url=urljoin("https://itch.io", url), title=title, start=start, end=end,
                 registration_deadline=end, format="online", participants=participants,
                 description=plain(raw.get("short_text") or raw.get("description")),
                 kind="game_jam", confidence=0.9, classified_by="source")


def _scan(page, url, events):
    """Load one listing page into `events`; return the jam URLs its cards show."""
    found = set()
    navigate(page, url, 'a[href*="/jam/"]')
    for _ in range(2):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        page.wait_for_timeout(200)
    for raw in embedded(page):
        event = schema_event(raw, "itchio", url, "game_jam")
        if event:
            events[event.url] = event
    for raw in script_objects(page):
        event = _calendar_event(raw)
        if event:
            events[event.url] = event
    cards = page.locator('.jam, .jam_cell').evaluate_all('''els => els.map(el => {
        const a=el.querySelector('h3 a[href*="/jam/"], .jam_title a, a.title');
        const date=el.querySelector('.date_countdown, time');
        return {url:a?.href,title:a?.textContent?.trim(),text:el.innerText,
            date:date?.getAttribute('title') || date?.getAttribute('datetime'),
            image:el.querySelector('img')?.src,
            hosts:[...el.querySelectorAll('.hosted_by a')].map(x=>x.textContent).join(', ')};
    })''')
    for raw in cards:
        if not raw.get("title") or not raw.get("url"):
            continue
        found.add(raw["url"])
        stamp = dt(raw.get("date"))
        text = raw.get("text", "")
        starts = "starts in" in text.lower()
        start, end = (stamp, None) if starts else (None, stamp)
        if not stamp or not upcoming(start, end):
            continue
        joined = re.search(r"([\d,]+)\s+joined", text)
        old = events.get(raw["url"])
        if old:
            old.organizer = raw.get("hosts") or old.organizer
            old.image = raw.get("image") or old.image
            if joined:
                old.participants = int(joined[1].replace(",", ""))
            continue
        events[raw["url"]] = Event(source="itchio", title=raw["title"], url=raw["url"],
            start=start, end=end, registration_deadline=end, format="online",
            description=plain(text), image=raw.get("image"), organizer=raw.get("hosts") or None,
            participants=int(joined[1].replace(",", "")) if joined else None,
            kind="game_jam", confidence=0.9, classified_by="source")
    check_block(page)
    return found


def _collect():
    events, seen = {}, set()
    with cdp_page() as page:
        _scan(page, SOURCE["url"], events)  # The calendar's embedded records.
        # The upcoming and in-progress lists are paged with ?page=N (about 25 jams
        # each): stop at the last page, an empty page, or one with no new jams.
        for listing in (SOURCE["url"] + "/upcoming", SOURCE["url"] + "/in-progress"):
            for n in range(1, MAX_PAGES + 1):
                found = _scan(page, listing if n == 1 else f"{listing}?page={n}", events)
                fresh, seen = found - seen, seen | found
                if not fresh or not page.locator("a.next_page").count():
                    break
            else:
                warn_limit(__name__, listing)
        if not events:
            raise RuntimeError("itch.io listing returned no parseable dated jams; markup may have changed")
    return sorted(events.values(), key=lambda e: (e.start is None, e.start.isoformat() if e.start else ""))
