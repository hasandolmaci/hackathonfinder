"""GovTech NL's Hackathon for Good calendar, embedded Wix public event records."""
import re
import time
from hackfinder.models import Event
from ._html_util import objects
from ._platforms_util import absolute, current, plain, utc
from ._signals_util import geo, signals
from ._vertical_util import client, robots

SOURCE = {"id": "govtechnl", "name": "GovTech NL", "url": "https://www.thehaguetech.com/hackathon-for-good",
          "method": "api", "default_kind": "mixed"}


def parse(html):
    events, found = {}, False
    for r in objects(html):
        if not r.get("title") or not isinstance(r.get("scheduling"), dict):
            continue
        found = True
        if not re.search(r"hackathon|hackaton|ideathon|coding competition|game jam|\bctf\b", r["title"], re.I):
            continue
        dates = r["scheduling"].get("config") or {}
        start, end = utc(dates.get("startDate")), utc(dates.get("endDate"))
        if not (start or end) or not current(start, end):
            continue
        loc = r.get("location") or {}
        coords, address = loc.get("coordinates") or {}, loc.get("fullAddress") or {}
        url = ((r.get("registration") or {}).get("external") or {}).get("registration")
        text = r.get("about") or r.get("description")
        e = Event(source="govtechnl", source_id=r["id"], title=r["title"],
            url=absolute(url or "/event-details/" + r["slug"], SOURCE["url"]), start=start, end=end,
            description=plain(text), image=(r.get("mainImage") or {}).get("url"),
            format="in-person" if loc.get("address") else "unknown", location=loc.get("address") or loc.get("name"),
            country=address.get("country"), organizer="The Hague Tech / GovTech NL",
            signals=signals(text=text, **geo(coords.get("lat"), coords.get("lng"), loc.get("address"))))
        events[e.url] = e
    if not found:
        raise RuntimeError("GovTech NL calendar has no Wix event records")
    return list(events.values())


def collect():
    with client(timeout=20) as c:
        robots(c, SOURCE["url"])
        time.sleep(1.1)
        r = c.get(SOURCE["url"])
        r.raise_for_status()
        return parse(r.text)
