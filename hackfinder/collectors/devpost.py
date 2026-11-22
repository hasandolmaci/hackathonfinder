"""Live Devpost listing JSON. Display dates describe the submission period."""
from datetime import datetime, timezone
import re

from hackfinder.models import Event
from ._signals_util import source_signals
from ._platforms_util import MAX_PAGES, absolute, check_robots, client, current, json_response, number, plain, warn_limit

SOURCE = {"id": "devpost", "name": "Devpost", "url": "https://devpost.com/hackathons",
          "method": "api", "default_kind": "hackathon"}
API = "https://devpost.com/api/hackathons"


def _dates(value):
    """Expand abbreviated ranges: Nov 11 - 30, 2026; Dec 30, 2026 - Jan 2, 2027."""
    value = (value or "").replace("–", "-").replace("—", "-")
    sides = re.split(r"\s+-\s+", value)
    years = re.findall(r"\b(20\d{2})\b", value)
    if not years:
        return None, None
    def parse(text, year, month=None):
        text = re.sub(r",?\s*20\d{2}", "", text).strip()
        if re.fullmatch(r"\d{1,2}", text) and month:
            text = month + " " + text
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(f"{text} {year}", fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return None
    start = parse(sides[0], years[0])
    end = parse(sides[-1], years[-1], start.strftime("%b") if start else None)
    if start and end and start > end and len(years) == 1:
        start = start.replace(year=start.year - 1)
    return start, end


def collect() -> list[Event]:
    events, seen = [], set()
    with client() as c:
        check_robots(c, API)
        for page in range(1, MAX_PAGES + 1):  # The server caps each page at 40, regardless of per_page.
            data = json_response(c.get(API, params=[("status[]", "open"), ("status[]", "upcoming"),
                                                   ("per_page", "40"), ("page", str(page))]))
            rows = data.get("hackathons")
            if not isinstance(rows, list):
                raise RuntimeError("Devpost JSON no longer contains hackathons")
            for row in rows:
                if row.get("open_state") not in ("open", "upcoming") or row["id"] in seen:
                    continue
                seen.add(row["id"])
                start, end = _dates(row.get("submission_period_dates"))
                if not current(start, end, date_only=True):
                    continue
                loc = (row.get("displayed_location") or {}).get("location") or ""
                mode = "online" if loc.lower() == "online" else "hybrid" if "hybrid" in loc.lower() else "in-person" if loc else "unknown"
                prize = plain(row.get("prize_amount"))
                usd = number(prize[1:]) if prize and prize.startswith("$") else None
                events.append(Event(source="devpost", signals=source_signals("devpost", row), source_id=str(row["id"]), title=plain(row["title"]),
                    url=absolute(row["url"], API), image=absolute(row.get("thumbnail_url"), API),
                    start=start, end=end, format=mode, location=None if mode == "online" else loc or None,
                    prize=prize, prize_usd=usd, participants=row.get("registrations_count"),
                    organizer=plain(row.get("organization_name")), tags=[x["name"] for x in row.get("themes", [])],
                    kind="hackathon", confidence=0.9, classified_by="source"))
            if not rows or page * 40 >= data.get("meta", {}).get("total_count", 0):
                break
        else:
            warn_limit(__name__, "open+upcoming")
    return events
