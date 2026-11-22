"""Official public CTFtime events API: https://ctftime.org/api/."""
import logging
from datetime import datetime, timedelta, timezone

from hackfinder.models import Event
from ._platforms_util import absolute, check_robots, client, current, json_response, plain, utc

SOURCE = {"id": "ctftime", "name": "CTFtime", "url": "https://ctftime.org",
          "method": "api", "default_kind": "ctf"}
API = "https://ctftime.org/api/v1/events/"


LIMIT = 1000
MARGIN = timedelta(days=45)  # The API wants start >= and finish <= : keep events that cross a window edge.


def _window(c, start, finish, rows):
    """Fetch one start window; split it in half while a response looks saturated."""
    data = json_response(c.get(API, params={"limit": LIMIT, "start": int(start.timestamp()),
                                            "finish": int((finish + MARGIN).timestamp())}))
    if not isinstance(data, list):
        raise RuntimeError("CTFtime events API did not return a list")
    if len(data) >= LIMIT and finish - start > timedelta(hours=1):
        logging.getLogger(__name__).info("saturated window %s..%s; splitting", start.date(), finish.date())
        mid = start + (finish - start) / 2
        _window(c, start, mid, rows)
        _window(c, mid, finish, rows)
        return
    for row in data:
        rows.setdefault(row["id"], row)


def collect() -> list[Event]:
    now = datetime.now(timezone.utc)
    # The first window reaches back so long-running CTFs that began before today
    # are included (the default API omits these); then 30-day windows for a year.
    edges = [now - timedelta(days=366)] + [now + timedelta(days=30 * i) for i in range(13)]
    rows: dict = {}
    with client() as c:
        check_robots(c, API)
        for start, finish in zip(edges, edges[1:]):
            _window(c, start, finish, rows)
    result = []
    for row in rows.values():
        start, end = utc(row.get("start")), utc(row.get("finish"))
        if not current(start, end):
            continue
        result.append(Event(source="ctftime", source_id=str(row["id"]), title=plain(row["title"]),
            url=absolute(row.get("ctftime_url"), SOURCE["url"]) or f"https://ctftime.org/event/{row['id']}/",
            description=plain(row.get("description")), image=absolute(row.get("logo"), SOURCE["url"]),
            start=start, end=end, format="in-person" if row.get("onsite") else "online",
            location=plain(row.get("location")) if row.get("onsite") else None,
            prize=plain(row.get("prizes")), participants=row.get("participants"),
            organizer=", ".join(x["name"] for x in row.get("organizers", [])) or None,
            tags=["security", "ctf"] + ([row["format"]] if row.get("format") else []),
            kind="ctf", confidence=0.9, classified_by="source"))
    return sorted(result, key=lambda e: e.start or datetime.max.replace(tzinfo=timezone.utc))
