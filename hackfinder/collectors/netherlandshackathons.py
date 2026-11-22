"""netherlandshackathons.com: Dutch aggregator (Astro site). Event URLs come from rss.xml plus the sitemap
(past events are dropped by date); every /events/<slug> page carries schema.org Event JSON-LD with dates,
address, price and the ORIGINAL registration URL (Luma/Eventbrite/organizer) in offers[0].url, which becomes
Event.url so dedupe merges it with our Luma/Eventbrite/Meetup rows. /go/ and /api/ are disallowed and never used."""
from __future__ import annotations

import json
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

from hackfinder.models import Event
from ._platforms_util import absolute, check_robots, client, current, plain, utc
from ._signals_util import signals

SOURCE = {"id": "netherlandshackathons", "name": "Hackathon Nederland", "url": "https://netherlandshackathons.com/",
          "method": "api", "default_kind": "hackathon"}
BASE = "https://netherlandshackathons.com"
LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
EVENT_RE = re.compile(r"<loc>\s*(https://netherlandshackathons\.com/events/[^<\s]+)\s*</loc>|<link>\s*(https://netherlandshackathons\.com/events/[^<\s]+)\s*</link>")
JAM_RE = re.compile(r"\bgame\s*jam\b", re.I)


def event_urls(*documents: str) -> list[str]:
    """Event page URLs from sitemap/RSS text (Dutch pages only, no /en/ duplicates). Pure."""
    return list(dict.fromkeys(m[1] or m[2] for text in documents for m in EVENT_RE.finditer(text)))


def parse_event(html: str) -> dict | None:
    """schema.org Event node of an event page, or None. Pure."""
    for block in LD_RE.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for node in data.get("@graph", [data]) if isinstance(data, dict) else data:
            if isinstance(node, dict) and node.get("@type") == "Event":
                return node
    return None


def _clean(url):
    if not url:
        return None
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")])
    return parts._replace(query=query).geturl()


def to_event(node: dict, page_url: str) -> Event | None:
    start, end = utc(node.get("startDate")), utc(node.get("endDate"))
    if not node.get("name") or not current(start, end):
        return None
    offers = [o for o in node.get("offers") or [] if isinstance(o, dict)]
    org = node.get("organizer") if isinstance(node.get("organizer"), dict) else {}
    link = next((o["url"] for o in offers if o.get("url")), None) or org.get("url")
    url = _clean(absolute(link, BASE)) or page_url
    if "netherlandshackathons.com/go/" in url:
        url = page_url
    place = (node.get("location") or {}).get("address") or {}
    city = place.get("addressLocality")
    online = "Online" in str(node.get("eventAttendanceMode", ""))
    location = None if online else ", ".join(x for x in (city, "Netherlands") if x)
    prices = [o["price"] for o in offers if isinstance(o.get("price"), (int, float))]
    paid = (max(prices) > 0) if prices else (False if node.get("isAccessibleForFree") else None)
    title = plain(node["name"], 300)
    jam = bool(JAM_RE.search(title + " " + (node.get("description") or "")[:200]))
    image = node.get("image")
    image = image[0] if isinstance(image, list) and image else image
    cur = next((o.get("priceCurrency") for o in offers if o.get("priceCurrency")), "EUR")
    return Event(source="netherlandshackathons", source_id=page_url.rstrip("/").split("/")[-1], url=url, title=title,
                 description=plain(node.get("description")), image=image if isinstance(image, str) else None,
                 start=start, end=end, format="online" if online else "in-person", location=location, country="Netherlands",
                 organizer=plain(org.get("name"), 200), kind="game_jam" if jam else "hackathon", confidence=0.9, classified_by="source",
                 signals=signals(text=node.get("description"), paid_entry=paid,
                                 entry_fee=f"{min(prices):g}-{max(prices):g} {cur}" if paid and prices else None,
                                 hosts=[org["name"]] if org.get("name") else None,
                                 registration_url=url if url != page_url else None))


def collect() -> list[Event]:
    events = {}
    with client() as c:
        check_robots(c, SOURCE["url"])
        docs = []
        for path in ("/rss.xml", "/sitemap.xml"):
            r = c.get(BASE + path, headers={"Accept": "application/xml"})
            if r.status_code in (401, 403, 429):
                raise RuntimeError(f"blocked: HTTP {r.status_code} from {r.url}")
            r.raise_for_status()
            docs.append(r.text)
        for page in event_urls(*docs):
            time.sleep(0.5)
            r = c.get(page, headers={"Accept": "text/html"})
            if r.status_code in (401, 403, 429):
                raise RuntimeError(f"blocked: HTTP {r.status_code} from {r.url}")
            if r.status_code != 200 or not (node := parse_event(r.text)):
                continue
            if event := to_event(node, page):
                events[event.source_id] = event
    return list(events.values())
