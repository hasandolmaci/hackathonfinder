"""Devnovate (India, student-heavy): the public JSON the React SPA loads, /api/v1/events.

One unpaginated response lists every event ever posted (~320, including workshops and
meetups, mostly past). Only approved events that are live/open and not yet over are kept.
Rows with eventType "hackathon" are kind=hackathon; anything else stays "unknown" for classify.py.
"""
from datetime import datetime, timezone
import re

from hackfinder.models import Event
from ._signals_util import source_signals
from ._platforms_util import absolute, check_robots, client, current, json_response, number, plain, utc

SOURCE = {"id": "devnovate", "name": "Devnovate", "url": "https://devnovate.co/events",
          "method": "api", "default_kind": "mixed"}
API = "https://devnovate.co/api/v1/events"
FORMATS = {"ONLINE": "online", "OFFLINE": "in-person", "HYBRID": "hybrid"}
NO_PRIZE = re.compile(r"^(tbd|tba|n/?a|nil|none|-)?$", re.I)


def _day(value):
    """DD-MM-YYYY, ISO date/datetime, or junk like '34 days left' -> UTC datetime or None."""
    value = (value or "").strip()
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", value)
    if m:
        try:
            return datetime(int(m[3]), int(m[2]), int(m[1]), tzinfo=timezone.utc)
        except ValueError:
            return None
    return utc(value) if re.match(r"\d{4}-\d{2}-\d{2}", value) else None


def _links(raw):
    """First http(s) registration/website link (the schema varies per row), else None."""
    for block in raw.get("links") or []:
        pairs = [(k, v) for k, v in block.items()] if isinstance(block, dict) else []
        for url in [v for k, v in pairs if k == "url"] + [v for k, v in pairs if k != "url" and k != "type"]:
            url = absolute(str(url), "https://") if str(url).startswith("http") else None
            if url and not re.search(r"whatsapp|instagram|linkedin|youtube|t\.me|discord", url):
                return url
    return None


def parse(rows: list) -> list[Event]:
    """Event rows -> live/upcoming Events (pure; testable offline)."""
    events = []
    for raw in rows:
        if raw.get("approvalStatus") != "approved" or not raw.get("eventName") or not raw.get("name"):
            continue
        start, end = _day(raw.get("startDate")), _day(raw.get("endDate"))
        deadline = _day(raw.get("registrationDeadline"))
        if not (raw.get("live") or raw.get("openStatus") == "OPEN") or not (start or end or deadline):
            continue
        if not current(start, end or deadline, date_only=True):
            continue
        fmt = FORMATS.get(raw.get("status"), "unknown")
        prize = (raw.get("prizePool") or "").strip()
        usd = re.fullmatch(r"\$\s?([\d,]+)|([\d,]+)\s?(?:\$|USD)", prize)
        hack = raw.get("eventType") == "hackathon"
        tags = list(raw.get("theme") or [])
        if raw.get("skillLevel"):
            tags.append(raw["skillLevel"])
        if raw.get("teamSize"):
            tags.append(f"team size {raw['teamSize']}")
        if raw.get("paid"):
            tags.append("paid")
        events.append(Event(
            source="devnovate", signals=source_signals("devnovate", raw), source_id=raw.get("_id"), url=f"https://devnovate.co/event/{raw['eventName']}",
            title=plain(raw["name"]), description=plain(raw.get("subtitle")),
            image=absolute(raw.get("cardImage") or raw.get("bannerImage"), "https://devnovate.co"),
            start=start, end=end, registration_deadline=deadline, format=fmt,
            location=None if fmt == "online" else plain(raw.get("location")),
            prize=None if NO_PRIZE.match(prize) else prize[:120],
            prize_usd=number((usd[1] or usd[2])) if usd else None,
            participants=raw.get("numberOfRegistrations") if isinstance(raw.get("numberOfRegistrations"), int) else None,
            organizer=raw.get("organizationName"), tags=tags[:12],
            kind="hackathon" if hack else "unknown", confidence=0.9 if hack else 0,
            classified_by="source" if hack else "none"))
    return events


def collect() -> list[Event]:
    with client() as c:
        check_robots(c, API)
        data = json_response(c.get(API, timeout=30))
    if not isinstance(data, list):
        raise RuntimeError("Devnovate events API returned no list; endpoint may have changed")
    return parse(data)
