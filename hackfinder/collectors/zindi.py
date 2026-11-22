"""Zindi public JSON API: open and upcoming data-science competitions (Africa-focused).

The list is sorted by start date, newest first, 10 per page. Rewards are strings such as
"$10 000 USD" or "R25 000 ZAR"; only USD amounts set prize_usd.
"""
from datetime import datetime, timezone
import re

from hackfinder.models import Event
from ._signals_util import source_signals
from ._platforms_util import MAX_PAGES, absolute, check_robots, client, current, json_response, number, plain, utc, warn_limit

SOURCE = {"id": "zindi", "name": "Zindi", "url": "https://zindi.africa/competitions",
          "method": "api", "default_kind": "coding_competition"}
API = "https://api.zindi.africa/v1/competitions"  # redirects to api.zindi.world


def parse(rows: list) -> list[Event]:
    """Competition rows -> open/upcoming Events (pure; testable offline)."""
    now, events = datetime.now(timezone.utc), []
    for row in rows:
        start, end = utc(row.get("start_time")), utc(row.get("entries_close_at") or row.get("end_time"))
        if not row.get("id") or not row.get("title") or not (row.get("open") or (end and end >= now)):
            continue
        reward = row.get("reward")
        usd = bool(reward and re.search(r"\$|USD", reward) and "€" not in reward)
        organizer = row.get("organization")
        events.append(Event(
            source="zindi", signals=source_signals("zindi", row), source_id=str(row["id"]), url=f"https://zindi.africa/competitions/{row['id']}",
            title=plain(row["title"]), description=plain(row.get("subtitle")), image=absolute(row.get("image"), API),
            start=start, end=utc(row.get("end_time")), registration_deadline=end, format="online",
            prize=reward if reward and re.search(r"[1-9]", reward) else None,
            prize_usd=number(re.sub(r"[^\d.]", "", reward)) if usd and reward else None,
            participants=row.get("participations_count") if isinstance(row.get("participations_count"), int) else None,
            organizer=organizer.get("name") if isinstance(organizer, dict) else organizer,
            tags=[t for t in ("beginner-friendly" if row.get("is_beginner_friendly") else None,
                              "team" if row.get("cohort") else None, row.get("kind")) if t],
            kind="coding_competition", confidence=0.9, classified_by="source"))
    return events


def collect() -> list[Event]:
    events = {}
    with client() as c:
        check_robots(c, API)
        for page in range(1, MAX_PAGES + 1):
            data = json_response(c.get(API, params={"page": page, "per_page": 10}))
            rows = data.get("data")
            if not isinstance(rows, list):
                raise RuntimeError("Zindi competitions API returned no data list; endpoint may have changed")
            if not rows:
                break
            for e in parse(rows):
                events[e.source_id] = e
            # Sorted by start date, newest first: a page with nothing open or upcoming ends the list.
            if not any(r.get("open") or current(utc(r.get("start_time")), utc(r.get("end_time"))) for r in rows):
                break
        else:
            warn_limit(__name__)
    return list(events.values())
