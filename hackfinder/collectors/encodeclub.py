"""Encode Club programmes: the /programmes page's own Supabase response, captured in the browser. Hackathon-type programmes only."""
import json

from hackfinder.browser import cdp_page
from hackfinder.models import Event
from ._signals_util import source_signals
from ._vertical_util import browser_worker, check_block, client, dt, plain, robots, upcoming

SOURCE = {"id": "encodeclub", "name": "Encode Club", "url": "https://www.encodeclub.com/programmes",
          "method": "scrape", "default_kind": "hackathon"}
FORMATS = {"online": "online", "in-person": "in-person", "hybrid": "hybrid"}


def collect() -> list[Event]:
    with client() as c:
        robots(c, SOURCE["url"])
    return browser_worker("encodeclub")


def _event(row):
    """One 'Encode Programmes' row -> Event; None for non-hackathons, unpublished or ended rows."""
    if (row.get("type") or "").lower() != "hackathon" or not row.get("published") or not row.get("slug"):
        return None
    start, end = dt(row.get("start date")), dt(row.get("end_date"))
    if not row.get("programme name") or not upcoming(start, end):
        return None
    fmt = FORMATS.get((row.get("location") or "").lower(), "unknown")
    tags = ["web3", *[x for x in (row.get("difficulty"), row.get("duration")) if x]]
    if row.get("is_team_based"):
        tags.append("team")
    return Event(source="encodeclub", signals=source_signals("encodeclub", row), source_id=str(row["id"]), title=plain(row["programme name"]),
        url=f"https://www.encodeclub.com/programmes/{row['slug']}",
        description=plain(row.get("tagline") or row.get("about_content")), image=row.get("image_hero") or row.get("image"),
        start=start, end=end, registration_deadline=dt(row.get("registration_deadline")), format=fmt,
        participants=row.get("total_registrations") or None, organizer="Encode Club", tags=tags,
        kind="hackathon", confidence=0.9, classified_by="source")


def _collect():
    rows = []
    with cdp_page() as page:
        def capture(response):
            if "supabase.co/rest/v1/Encode%20Programmes" in response.url and "select=*" in response.url:
                try:
                    rows.extend(json.loads(response.text()))
                except ValueError:
                    pass
        page.on("response", capture)
        page.goto(SOURCE["url"], wait_until="domcontentloaded", timeout=30000)
        check_block(page)
        for _ in range(20):
            if rows:
                break
            page.wait_for_timeout(1000)
    if not rows:
        raise RuntimeError("Encode Club programmes response was not captured; the site may have changed")
    events = {}
    for row in rows:
        event = _event(row)
        if event:
            events[event.url] = event
    return sorted(events.values(), key=lambda e: (e.start is None, e.start))
