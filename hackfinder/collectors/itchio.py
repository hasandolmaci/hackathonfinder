"""Rendered jam calendar and upcoming/in-progress cards; no HTML HTTP scraping."""
import re
import logging
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

from hackfinder.browser import cdp_page
from hackfinder.models import Event
from ._signals_util import source_signals
from ._vertical_util import (MAX_PAGES, browser_worker, check_block, client, dt, embedded,
                             plain, robots, schema_event, script_objects, upcoming, warn_limit)

SOURCE = {"id": "itchio", "name": "itch.io Jams", "url": "https://itch.io/jams",
          "method": "scrape", "default_kind": "game_jam"}


def _navigate(page, url):
    """Space page loads; try rate-limited pages at most three times, respecting Retry-After."""
    for attempt in range(3):
        page.wait_for_timeout(random.uniform(2000, 3000))
        response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
        if response is None or response.status != 429:
            break
        if attempt == 2:
            raise RuntimeError(f"blocked: HTTP 429 at {url}")
        value = response.headers.get("retry-after", "")
        try:
            delay = max(0, float(value))
        except ValueError:
            try:
                delay = max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                delay = 0
        page.wait_for_timeout(1000 * max(delay, 5 * 2 ** attempt) + random.uniform(0, 500))
    if response and response.status >= 400:
        raise RuntimeError(f"HTTP {response.status} at {url}")
    page.wait_for_selector("body", timeout=8000)
    check_block(page)
    page.wait_for_selector('a[href*="/jam/"]', timeout=12000)


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
    return Event(source="itchio", signals=source_signals("itchio", raw), source_id=str(raw["id"]) if raw.get("id") else None,
                 url=urljoin("https://itch.io", url), title=title, start=start, end=end,
                 registration_deadline=end, format="online", participants=participants,
                 description=plain(raw.get("short_text") or raw.get("description")),
                 kind="game_jam", confidence=0.9, classified_by="source")


def _scan(page, url, events):
    """Load one listing page into `events`; return the jam URLs its cards show."""
    found = set()
    _navigate(page, url)
    for _ in range(2):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        page.wait_for_timeout(200)
    for raw in embedded(page):
        event = schema_event(raw, "itchio", url, "game_jam")
        if event:
            event.signals.update(source_signals("itchio", raw))
            events[event.url] = event
    for raw in script_objects(page):
        event = _calendar_event(raw)
        if event:
            events[event.url] = event
    cards = page.locator('.jam, .jam_cell').evaluate_all('''els => els.map(el => {
        const a=el.querySelector('h3 a[href*="/jam/"], .jam_title a, a.title');
        const date=el.querySelector('.date_countdown, time');
        return {url:a?.href,title:a?.textContent?.trim(),text:el.innerText,
            date:date?.getAttribute('title') || date?.getAttribute('datetime') || date?.textContent,
            image:el.querySelector('img')?.src,
            hosts:[...el.querySelectorAll('.hosted_by a')].map(x=>x.textContent.trim())};
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
        entries = re.search(r"([\d,]+)\s+(?:submissions|entries)", text)
        evidence = source_signals("itchio", {**raw,
            "joined": int(joined[1].replace(",", "")) if joined else None,
            "entries": int(entries[1].replace(",", "")) if entries else None})
        hosts = ", ".join(raw.get("hosts") or []) or None
        old = events.get(raw["url"])
        if old:
            old.organizer = hosts or old.organizer
            old.signals.update(evidence)
            old.image = raw.get("image") or old.image
            if joined:
                old.participants = int(joined[1].replace(",", ""))
            continue
        events[raw["url"]] = Event(source="itchio", title=raw["title"], url=raw["url"],
            start=start, end=end, registration_deadline=end, format="online",
            description=plain(text), image=raw.get("image"), organizer=hosts, signals=evidence,
            participants=int(joined[1].replace(",", "")) if joined else None,
            kind="game_jam", confidence=0.9, classified_by="source")
    check_block(page)
    return found


def _collect():
    events, seen = {}, set()
    with cdp_page() as page:
        try:
            _scan(page, SOURCE["url"], events)  # The calendar's embedded records.
            _listings(page, events, seen)
        except RuntimeError as exc:
            if not events or "429" not in str(exc):
                raise
            logging.getLogger(__name__).warning("itch.io rate limited; keeping %d jams: %s", len(events), exc)
        if not events:
            raise RuntimeError("itch.io listing returned no parseable dated jams; markup may have changed")
    return sorted(events.values(), key=lambda e: (e.start is None, e.start.isoformat() if e.start else ""))


def _listings(page, events, seen):
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
