"""WhereUElevate's public paginated challenge directory."""
from hackfinder.models import Event
from ._platforms_util import absolute, current, plain, utc
from ._signals_util import count, flag, geo, reward, signals
from ._vertical_util import MAX_PAGES, client, polite_json, robots, warn_limit

SOURCE = {"id": "whereuelevate", "name": "Where U Elevate", "url": "https://whereuelevate.com/drills",
          "method": "api", "default_kind": "mixed"}
API = "https://api-academia.whereuelevate.com/wuelev8/api/v1/drills/search"


def _event(r):
    start, end = utc(r.get("startTs")), utc(r.get("endTs"))
    if not r.get("customUrl") or not r.get("drillName") or not (start or end) or not current(start, end) or r.get("hidden"):
        return None
    if r.get("status") not in ("LIVE", "UPCOMING"):
        return None
    reg, venue = r.get("drillRegistration") or {}, r.get("venue") or {}
    if not isinstance(venue, dict):
        venue = {"name": str(venue)}
    fmt = {"ONLINE": "online", "OFFLINE": "in-person", "IN_PERSON": "in-person", "HYBRID": "hybrid"}.get(r.get("mode"), "unknown")
    image = next((v.get("url") for a in (r.get("mediaAssets") or {}).get("assets", [])
                  if a.get("type") in ("BANNER", "THUMBNAIL") for v in a.get("variants", []) if v.get("url")), None)
    participants = count((r.get("enrollmentStats") or {}).get("totalRegistrations"))
    return Event(source="whereuelevate", source_id=r["drillId"], title=r["drillName"],
        url=absolute(reg.get("externalRegistrationLink") or "/drills/" + r["customUrl"], SOURCE["url"]),
        start=start, end=end, registration_deadline=utc(reg.get("registrationEndTs")), image=image,
        description=plain(r.get("description")), format=fmt, location=venue.get("name") if fmt != "online" else None,
        country=venue.get("country") if fmt != "online" else None, prize=r.get("totalPrizeValue"), participants=participants,
        organizer=(r.get("organizer") or {}).get("name"), signals=signals(text=r.get("description") or "\n".join(
            str(r[k]) for k in ("drillName", "category", "subCategory", "purpose") if r.get(k)),
            registrations=participants, paid_entry=flag(r.get("paid")), **reward((r.get("totalPrizeValue") or "").replace("₹", "INR ")),
            **geo(venue.get("latitude"), venue.get("longitude"))))


def collect():
    events, seen = {}, set()
    with client(timeout=20) as c:
        robots(c, SOURCE["url"])
        for page in range(MAX_PAGES):
            data = polite_json(c, API, params={"searchProfile": "LISTING", "categories": "HACKATHON", "limit": 20,
                "offset": page, "status": ["LIVE", "UPCOMING"], "hidden": "false", "order": "displayOrder.desc"})
            block = data.get("result") or {}
            rows = block.get("content")
            if not isinstance(rows, list):
                raise RuntimeError("WhereUElevate search no longer returns content")
            fresh = [r for r in rows if r["drillId"] not in seen]
            seen.update(r["drillId"] for r in fresh)
            for r in fresh:
                if e := _event(r):
                    events[e.url] = e
            if not fresh or block.get("last") or page + 1 >= block.get("totalPages", MAX_PAGES + 1):
                break
        else:
            warn_limit(__name__)
    return list(events.values())
