"""Junction platform tRPC (hackjunction.app): the main event, JunctionX and Hackathon for Good editions."""
import json

from hackfinder.models import Event
from ._signals_util import source_signals
from ._platforms_util import absolute, check_robots, client, current, json_response, plain, utc

SOURCE = {"id": "hackjunction", "name": "Hack Junction", "url": "https://hackjunction.app/hackathons",
          "method": "api", "default_kind": "hackathon"}
API = "https://hackjunction.app/api/trpc/"
PROCEDURES = ["event.getAllFutureEvents", "event.getAllFeaturedEvents", "event.getAllPastEvents"]
FORMATS = {"online": "online", "physical": "in-person", "hybrid": "hybrid"}


def _event(row):
    start, end = utc(row.get("startTime")), utc(row.get("endTime"))
    if not row.get("slug") or row.get("eventStatus") != "published" or not current(start, end):
        return None
    tags = [f"team:{row['maxTeamSize']}"] if row.get("maxTeamSize") else []
    return Event(source="hackjunction", signals=source_signals("hackjunction", row), source_id=str(row["id"]), title=plain(row["name"]),
        url=f"https://hackjunction.app/hackathons/{row['slug']}", description=plain(row.get("description")),
        image=absolute(row.get("coverImage") or row.get("logo"), SOURCE["url"]), start=start, end=end,
        registration_deadline=utc(row.get("registrationEndTime")),
        format=FORMATS.get(row.get("eventType"), "unknown"), organizer="Junction", tags=tags,
        kind="hackathon", confidence=0.9, classified_by="source")


def collect() -> list[Event]:
    batch = {str(i): {"json": None, "meta": {"values": ["undefined"]}} for i in range(len(PROCEDURES))}
    events, seen = [], set()
    with client() as c:
        check_robots(c, SOURCE["url"])
        data = json_response(c.get(API + ",".join(PROCEDURES), params={"batch": "1", "input": json.dumps(batch)}))
        if not isinstance(data, list):
            raise RuntimeError("Junction tRPC response changed")
        for part in data:
            rows = ((part.get("result") or {}).get("data") or {}).get("json")
            if not isinstance(rows, list):
                raise RuntimeError("Junction tRPC no longer returns event lists")
            for row in rows:
                if row.get("id") not in seen:
                    seen.add(row.get("id"))
                    events += [e for e in [_event(row)] if e]
    return events
