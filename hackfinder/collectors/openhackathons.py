"""Salesforce community upcoming events. NEEDS LIVE BROWSER TEST.
The HTTP response is only an app shell; read public rendered pages through cdp_page.
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from hackfinder.models import Event
from ._country_sites import clean_url, parse_event, to_event as schema_event
from ._platforms_util import MAX_PAGES, absolute, check_robots, client, current, plain, utc, warn_limit
from ._signals_util import signals
from ._vertical_util import check_block

SOURCE = {"id": "openhackathons", "name": "Open Hackathons", "url": "https://www.openhackathons.org/s/upcoming-events",
          "method": "scrape", "default_kind": "mixed"}  # also publishes training bootcamps


def event_urls(html):
    return list(dict.fromkeys(u for a in HTMLParser(html).css('a[href]')
        if (u := absolute(a.attributes.get("href"), SOURCE["url"]))
        and re.match(r"/s/siteevent/[A-Za-z0-9]+/", urlsplit(u).path)))


def _date(value):
    if not value:
        return None
    if d := utc(value):
        return d
    value = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", value.strip())
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def parse_detail(html, page_url):
    if node := parse_event(html):
        event = schema_event(node, page_url, "openhackathons", None)
        if event:
            event.kind, event.confidence, event.classified_by = "unknown", 0.0, "none"
        return event
    tree = HTMLParser(html)
    heading = tree.css_first("h1")
    if not heading:
        raise RuntimeError("Open Hackathons detail has no rendered heading")
    title = plain(heading.text())
    if not re.search(r"hackathon", title, re.I):
        return None
    fields = {}
    for n in tree.css("dt, th, .slds-form-element__label"):
        if n.next:
            fields[(plain(n.text()) or "").lower().rstrip(":")] = plain(n.next.text(), 3000)
    lines = [s.strip() for s in tree.text(separator="\n").splitlines() if s.strip()]
    labels = ("start date", "end date", "event start date", "event end date", "application deadline",
              "location", "country", "organizer", "event format")
    for i, line in enumerate(lines[:-1]):
        if line.lower().rstrip(":") in labels:
            fields.setdefault(line.lower().rstrip(":"), lines[i + 1])
    start = _date(fields.get("start date") or fields.get("event start date"))
    end = _date(fields.get("end date") or fields.get("event end date"))
    if not (start or end):
        raise RuntimeError("Open Hackathons date labels changed; needs live parser review")
    if not current(start, end, date_only=True):
        return None
    url = page_url
    for a in tree.css("a[href]"):
        if re.fullmatch(r"apply(?: now)?|register(?: now)?|registration", a.text(strip=True), re.I):
            link = absolute(a.attributes.get("href"), page_url)
            if link and not any(p in link for p in ("/login", "/secur/")):
                url = clean_url(link)
                break
    fmt = {"online": "online", "virtual": "online", "in-person": "in-person", "hybrid": "hybrid"}.get((fields.get("event format") or "").lower(), "unknown")
    body = tree.css_first("main, [role=main]") or tree.body
    text = body.text() if body else None
    return Event(source="openhackathons", source_id=page_url.split("/siteevent/")[-1].split("/")[0], url=url,
        title=title, start=start, end=end, registration_deadline=_date(fields.get("application deadline")),
        format=fmt, location=None if fmt == "online" else fields.get("location"), country=fields.get("country"),
        organizer=fields.get("organizer"), description=plain(text), signals=signals(text=text))


def collect():
    from hackfinder.browser import cdp_page
    with client() as c:
        check_robots(c, SOURCE["url"])
    events, links, seen = {}, [], set()
    with cdp_page() as page:
        page.goto(SOURCE["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        for _ in range(MAX_PAGES):
            check_block(page)
            found = [u for u in event_urls(page.content()) if u not in seen]
            seen.update(found)
            links.extend(found)
            nxt = page.get_by_role("button", name=re.compile(r"^(next|load more|show more)$", re.I))
            if not nxt.count() or not nxt.first.is_enabled():
                break
            if not found:
                raise RuntimeError("Open Hackathons pagination stalled")
            nxt.first.click()
            page.wait_for_timeout(1500)
        else:
            warn_limit(__name__)
        if not links and not re.search(r"no (?:upcoming )?events|no records", page.inner_text("body"), re.I):
            raise RuntimeError("Open Hackathons listing has no rendered event links")
        for url in links:
            page.wait_for_timeout(1100)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            check_block(page)
            if event := parse_detail(page.content(), url):
                events[event.source_id] = event
    return list(events.values())
