"""Commudle public hackathon JSON (India communities). Upcoming list plus recent past pages for hackathons still running."""
from datetime import datetime, timedelta, timezone

from hackfinder.models import Event
from ._signals_util import source_signals
from ._platforms_util import MAX_PAGES, absolute, check_robots, client, current, json_response, plain, utc, warn_limit

SOURCE = {"id": "commudle", "name": "Commudle", "url": "https://www.commudle.com/hackathons",
          "method": "api", "default_kind": "hackathon"}
API = "https://json.commudle.com/api/v2/hackathons/public/all_hackathons"
FORMATS = {"online": "online", "offline": "in-person", "hybrid": "hybrid"}


def _event(row):
    start, end = utc(row.get("start_date")), utc(row.get("end_date"))
    community = row.get("community") or {}
    if not row.get("slug") or not community.get("slug") or not current(start, end):
        return None
    prizes = {k: v for k, v in (row.get("total_prize_amount") or {}).items() if v}
    prize = ", ".join(f"{k} {v:,.0f}" for k, v in prizes.items()) or None
    tags = [x for x in (row.get("hackathon_theme"), row.get("participate_types")) if x]
    if row.get("max_number_of_teammates"):
        tags.append(f"team:{row.get('min_number_of_teammates') or 1}-{row['max_number_of_teammates']}")
    if row.get("interested_members_count"):
        tags.append(f"interested:{row['interested_members_count']}")
    return Event(source="commudle", signals=source_signals("commudle", row), source_id=str(row["id"]),
        url=f"https://www.commudle.com/communities/{community['slug']}/hackathons/{row['slug']}",
        title=plain(row["name"]), description=plain(row.get("tagline") or row.get("description")),
        image=absolute((row.get("banner_image") or {}).get("url"), SOURCE["url"]), start=start, end=end,
        format=FORMATS.get(row.get("hackathon_location_type"), "unknown"), prize=prize,
        prize_usd=prizes.get("USD"), participants=row.get("number_of_participants") or None,
        organizer=plain(community.get("name")), tags=tags, kind="hackathon", confidence=0.9, classified_by="source")


def _listing(c, when, events, seen):
    """Cursor-paginate one list; the past list is newest first, so stop once it is older than 120 days."""
    after, floor = None, datetime.now(timezone.utc) - timedelta(days=120)
    for _ in range(MAX_PAGES):
        params = {"when": when, "limit": 50, **({"after": after} if after else {})}
        block = json_response(c.get(API, params=params)).get("data")
        if not isinstance(block, dict) or not isinstance(block.get("page"), list):
            raise RuntimeError("Commudle JSON no longer contains hackathons")
        rows = [r["data"] for r in block["page"] if r["data"]["id"] not in seen]
        seen.update(r["id"] for r in rows)
        events += [e for e in map(_event, rows) if e]
        info = block.get("page_info") or {}
        oldest = min((utc(r.get("start_date")) or floor for r in rows), default=floor)
        if not rows or not info.get("has_next_page") or not info.get("end_cursor") or (when == "past" and oldest < floor):
            return
        after = info["end_cursor"]
    warn_limit(__name__, when)


def collect() -> list[Event]:
    events, seen = [], set()
    with client() as c:
        check_robots(c, API)
        for when in ("future", "past"):
            _listing(c, when, events, seen)
    return events
