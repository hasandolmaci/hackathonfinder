"""Hack2skill (India, corporate/Google programs): the public JSON its home page loads.

/api/v1/innovator/public/event/list returns flagship + community events in one response
(registration window, mode, ticket, team size, registrations). Events whose registration is
open or upcoming then get /api/v1/event/<url>/event-details for the program type
(HACKATHON, ...) and submission window. Non-hackathon types stay "unknown" for classify.py.
"""
from datetime import datetime, timezone
import time

from hackfinder.models import Event
from ._signals_util import source_signals
from ._platforms_util import absolute, check_robots, client, json_response, plain, utc

SOURCE = {"id": "hack2skill", "name": "Hack2skill", "url": "https://hack2skill.com/hackathons-listing",
          "method": "api", "default_kind": "mixed"}
BASE = "https://hack2skill.com"
LIST_API = BASE + "/api/v1/innovator/public/event/list"
FORMATS = {"VIRTUAL": "online", "ONLINE": "online", "IN_PERSON": "in-person", "HYBRID": "hybrid"}


def parse(data: dict, details: dict | None = None) -> list[Event]:
    """List payload (+ {eventUrl: event-details data}) -> Events with an open/upcoming registration. Pure."""
    now, events = datetime.now(timezone.utc), []
    for group in ("flagshipEvents", "communityEvents"):
        for raw in data.get(group) or []:
            slug, title = raw.get("eventUrl"), plain(raw.get("title"))
            deadline = utc(raw.get("registrationEnd"))
            if not slug or not title or raw.get("status") != "APPROVED" or not deadline or deadline < now:
                continue
            detail = (details or {}).get(slug) or {}
            tags = raw.get("tags") or {}
            mode = (tags.get("mode") or {}).get("value")
            team = tags.get("teamSize") or {}
            reg = (tags.get("registrations") or {}).get("value")
            hack = detail.get("type") == "HACKATHON"
            extra = [f"{team['min']}-{team['max']} per team" if team.get("max") and team["max"] > 1 else None,
                     "free" if (tags.get("ticket") or {}).get("value") == "FREE" else "paid" if tags.get("ticket") else None,
                     raw.get("flag", "").lower() or None]
            events.append(Event(
                source="hack2skill", signals=source_signals("hack2skill", raw, detail), source_id=slug, url=f"{BASE}/event/{slug}", title=title,
                image=absolute(raw.get("thumbnail"), BASE),
                start=utc(detail.get("submissionStart") or raw.get("registrationStart")),
                end=utc(detail.get("submissionEnd")) or deadline, registration_deadline=deadline,
                format=FORMATS.get(mode, "unknown"),
                participants=reg if isinstance(reg, int) and reg else None,
                tags=[t for t in extra if t],
                kind="hackathon" if hack else "unknown", confidence=0.9 if hack else 0,
                classified_by="source" if hack else "none"))
    return events


def collect() -> list[Event]:
    with client() as c:
        check_robots(c, LIST_API)
        payload = json_response(c.get(LIST_API, params={"page": 1, "records": 100}))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Hack2skill event list API returned no data; endpoint may have changed")
        details = {}
        for e in parse(data):
            time.sleep(0.6)  # one event-details request per open/upcoming event
            r = c.get(f"{BASE}/api/v1/event/{e.source_id}/event-details")
            if r.status_code == 200:
                details[e.source_id] = (r.json() or {}).get("data") or {}
    return parse(data, details)
