"""2hero's complete public site bundle; hackathon programs only."""
import time
from hackfinder.models import Event
from ._platforms_util import absolute, current, plain, utc
from ._signals_util import names, signals
from ._vertical_util import client, polite_json, robots

SOURCE = {"id": "twohero", "name": "2hero", "url": "https://2hero.dev/hackathons",
          "method": "api", "default_kind": "hackathon"}
API = "https://2hero.dev/apply/site/bundle"


def parse(data):
    if not isinstance(data.get("programs"), list):
        raise RuntimeError("2hero bundle has no programs")
    companies = {r["organization"]: r for r in data.get("companies", [])}
    venues = {r["venue"]: r for r in data.get("venues", [])}
    events = []
    for r in data["programs"]:
        start, end = utc(r.get("starts")), utc(r.get("ends"))
        if ((r.get("programKind") or {}).get("kind") != "hackathon" or (r.get("state") or {}).get("kind") in ("closed", "draft")
                or not r.get("slug") or not (start or end) or not current(start, end)):
            continue
        venue = venues.get(r.get("venueId"), {})
        place = ", ".join(x for x in [venue.get("name"), venue.get("city") or r.get("locationCity"), venue.get("country")] if x)
        hosts = names([companies[x] for x in r.get("hostCompanyIds", []) if x in companies])
        sponsors = names([companies[x] for x in r.get("sponsorCompanyIds", []) if x in companies])
        themes = [x["label"] for x in r.get("skills", []) if x.get("label")]
        online = "online" in " ".join(str(r.get(k) or "") for k in ("name", "locationTitle")).lower()
        events.append(Event(source="twohero", source_id=r["program"], title=r["name"],
            url=absolute((r.get("page") or {}).get("actionUrl") or "/hackathons/" + r["slug"], SOURCE["url"]),
            start=start, end=end, description=plain(r.get("description") or r.get("contentHtml")),
            image=absolute(r.get("bannerUrl"), SOURCE["url"]), location=None if online else place or None,
            country=None if online else venue.get("country"), format="online" if online else "in-person" if place else "unknown",
            organizer=", ".join(hosts) or "2hero", tags=themes,
            signals=signals(text=r.get("contentHtml") or r.get("description"), sponsors=sponsors or None, themes=themes or None),
            kind="hackathon", confidence=0.9, classified_by="source"))
    return events


def collect():
    with client(timeout=20) as c:
        robots(c, SOURCE["url"])
        time.sleep(1.1)
        return parse(polite_json(c, API))
