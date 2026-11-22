"""Public frontend JSON; the separate dash backend forbids bots in robots.txt.

The Next.js deployment ID may rotate. Set HF_HACKCLUB_BUILD_ID to the current
public frontend deployment if a deployment retires this JSON URL. Fail visibly
rather than falling back to the robots-disallowed backend or stale local data.
"""
import os

from hackfinder.models import Event
from ._platforms_util import absolute, check_robots, client, current, json_response, plain, utc

SOURCE = {"id": "hackclub", "name": "Hack Club", "url": "https://hackathons.hackclub.com",
          "method": "api", "default_kind": "hackathon"}


def collect() -> list[Event]:
    build = os.getenv("HF_HACKCLUB_BUILD_ID", "FM7io0gaOJ4Y3hxo7QuGE")
    url = f"https://hackathons.hackclub.com/_next/data/{build}/index.json"
    with client() as c:
        check_robots(c, url)
        r = c.get(url)
        if r.status_code == 404:
            raise RuntimeError("Hack Club frontend deployment changed: update HF_HACKCLUB_BUILD_ID")
        data = json_response(r)
    rows = data.get("pageProps", {}).get("events")
    if not isinstance(rows, list):
        raise RuntimeError("Hack Club frontend JSON no longer contains pageProps.events")
    result, seen = [], set()
    for row in rows:
        start, end = utc(row.get("start")), utc(row.get("end"))
        if not current(start, end) or row["id"] in seen:
            continue
        seen.add(row["id"])
        mode = "hybrid" if row.get("hybrid") else "online" if row.get("virtual") else "in-person"
        result.append(Event(source="hackclub", source_id=str(row["id"]), title=plain(row["name"]),
            url=absolute(row.get("website"), SOURCE["url"]) or f"https://hackathons.hackclub.com/?event={row['id']}",
            image=absolute(row.get("banner") or row.get("logo"), SOURCE["url"]), start=start, end=end,
            format=mode, location=None if mode == "online" else ", ".join(dict.fromkeys(
                x for x in (row.get("city"), row.get("state"), row.get("country")) if x)) or None,
            country=row.get("country") if mode != "online" else None, tags=["student", "high-school"],
            kind="hackathon", confidence=0.9, classified_by="source"))
    return result
