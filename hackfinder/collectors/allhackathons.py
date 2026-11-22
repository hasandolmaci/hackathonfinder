"""allhackathons.com: server-rendered aggregator list (/hackathons/?page=N) + one detail page per live event.

The list is sorted by start date, newest first (a few future "Date TBD" rows lead), so
paging stops at the first page whose dated rows are all in the past. Each upcoming/current
row then gets its /hackathon/<slug>/ page, which shows themes, location, organizer, prize and
the ORIGINAL registration site: that becomes Event.url (utm_* dropped) so dedupe can merge
this aggregator with Devpost/Unstop/Luma; without one, the allhackathons page is the URL.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from hackfinder.models import Event
from ._signals_util import source_signals
from ._platforms_util import MAX_PAGES, absolute, check_robots, client, current, number, plain, warn_limit

SOURCE = {"id": "allhackathons", "name": "allhackathons.com", "url": "https://allhackathons.com/hackathons/",
          "method": "api", "default_kind": "hackathon"}
BASE = "https://allhackathons.com"
FORMATS = {"online": "online", "in-person": "in-person", "hybrid": "hybrid"}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_RE = re.compile(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})")


def _date(text):
    m = DATE_RE.search(text or "")
    if not m or m[1].lower() not in MONTHS:
        return None
    try:
        return datetime(int(m[3]), MONTHS[m[1].lower()], int(m[2]), tzinfo=timezone.utc)
    except ValueError:
        return None


def _dates(text):
    """'Jan. 27, 2027 - Jan. 29, 2027' -> (start, end); a single date gives (d, d)."""
    found = [_date(x) for x in DATE_RE.sub(lambda m: m[0] + "\n", text or "").splitlines()]
    found = [d for d in found if d]
    return (found[0], found[-1]) if found else (None, None)


def parse_list(html: str) -> list[dict]:
    """List page -> one dict per card: slug, title, start, end, format, themes, description, image. Pure."""
    rows = []
    for card in HTMLParser(html).css("div.row.align-items-center.bg-white.mb-4"):
        link = card.css_first("a.h5")
        if not link or "/hackathon/" not in link.attributes.get("href", ""):
            continue
        slug = link.attributes["href"].strip("/").split("/")[-1]
        badge = card.css_first("span.badge")
        para = card.css_first("div.col-lg-7 > p:not(.text-muted)")
        start, end = _dates(para.text() if para else "")
        image = card.css_first("img")
        rows.append({
            "slug": slug, "title": plain(link.text()), "start": start, "end": end,
            "format": FORMATS.get((badge.text(strip=True) if badge else "").lower(), "unknown"),
            "themes": [a.text(strip=True) for a in card.css('a[href^="/themes/"]')],
            "description": plain(card.css_first("p.text-muted.mt-2").text()) if card.css_first("p.text-muted.mt-2") else None,
            "image": absolute(image.attributes.get("src"), BASE) if image else None})
    return rows


def _card(tree, heading):
    """Text of the sidebar card whose <h5> contains `heading` (Location, Organizer, Prizes ...)."""
    for h5 in tree.css("h5.card-title"):
        if heading in h5.text():
            body = h5.parent.css_first("div.text-muted")
            return plain(body.text()) if body else None
    return None


def parse_detail(html: str) -> dict:
    """Detail page -> website, location, organizer, prize, description, themes. Pure."""
    tree = HTMLParser(html)
    site = next((a.attributes.get("href") for a in tree.css("a[onclick*=trackWebsiteClick]")), None)
    if site:  # utm_* tags only mark the aggregator referral
        parts = urlsplit(site)
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")])
        site = parts._replace(query=query).geturl()
    desc = tree.css_first("div.card-body > div.text-muted.lh-lg")
    where = _card(tree, "Location")
    header = tree.css_first("div.d-flex.align-items-center.mb-3 span.fw-medium")
    return {"website": absolute(site, BASE) if site else None,
            "location": unquote(where) if where else None,
            "place": plain(header.text()) if header else None,
            "organizer": _card(tree, "Organizer"), "prize": _card(tree, "Prize"),
            "description": plain(desc.text()) if desc else None,
            "text": plain(desc.text(), 3000) if desc else None,
            "themes": [a.text(strip=True) for a in tree.css('a.badge[href^="/themes/"]')]}


def _event(row: dict, detail: dict) -> Event:
    online = row["format"] == "online"
    place = detail.get("location") if not online else None
    if not place and not online and detail.get("place") and detail["place"].lower() not in FORMATS:
        place = detail["place"]  # the header shows a country/region when no address is given
    prize = detail.get("prize")
    amount = number(re.sub(r"[$,\s]", "", prize)) if prize and prize.startswith("$") else None
    if prize and not re.search(r"[1-9]", prize):
        prize = None  # "$0" / "None" placeholders
    url = detail.get("website") or f"{BASE}/hackathon/{row['slug']}/"
    return Event(source="allhackathons", signals=source_signals("allhackathons", row, detail), source_id=row["slug"], url=url, title=row["title"],
                 description=detail.get("description") or row["description"], image=row["image"],
                 start=row["start"], end=row["end"], format=row["format"], location=place,
                 prize=prize, prize_usd=amount if prize and amount else None,
                 organizer=detail.get("organizer") or None, tags=detail.get("themes") or row["themes"],
                 kind="hackathon", confidence=0.9, classified_by="source")


def collect() -> list[Event]:
    events, stalled = {}, 0
    with client() as c:
        check_robots(c, SOURCE["url"])
        headers = {"Accept": "text/html"}
        for page in range(1, MAX_PAGES + 1):
            r = c.get(SOURCE["url"], params={"page": page}, headers=headers)
            if r.status_code in (401, 403, 429):
                raise RuntimeError(f"blocked: HTTP {r.status_code} from {r.url}")
            r.raise_for_status()
            rows = parse_list(r.text)
            if not rows:
                break
            dated = [x for x in rows if x["start"]]
            live = [x for x in rows if x["start"] and current(x["start"], x["end"], date_only=True)]
            for row in live:
                if row["slug"] in events:
                    continue
                time.sleep(0.6)  # one detail request per live event
                d = c.get(f"{BASE}/hackathon/{row['slug']}/", headers=headers)
                if d.status_code in (401, 403, 429):
                    raise RuntimeError(f"blocked: HTTP {d.status_code} from {d.url}")
                events[row["slug"]] = _event(row, parse_detail(d.text) if d.status_code == 200 else {})
            # Date-sorted list: a page with dated rows but none live means the rest is past.
            stalled = 0 if live or not dated else stalled + 1
            if stalled >= 1:
                break
            time.sleep(0.6)
        else:
            warn_limit(__name__)
    return list(events.values())
