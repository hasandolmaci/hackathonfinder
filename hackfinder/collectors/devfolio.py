"""Public Devfolio search API used by the hackathon directory."""
from hackfinder.models import Event
from ._signals_util import source_signals
from ._platforms_util import MAX_PAGES, absolute, check_robots, client, current, json_response, plain, utc, warn_limit

SOURCE = {"id": "devfolio", "name": "Devfolio", "url": "https://devfolio.co/hackathons",
          "method": "api", "default_kind": "hackathon"}
API = "https://api.devfolio.co/api/search/hackathons"
SIZE = 100


def _event(row):
    settings = row.get("hackathon_setting") or {}
    start, end = utc(row.get("starts_at")), utc(row.get("ends_at"))
    if not current(start, end) or row.get("private"):
        return None
    slug = settings.get("subdomain") or row.get("slug")
    if not slug:
        raise RuntimeError("Devfolio listing is missing its canonical subdomain")
    # Prize records include credits, memberships and sponsor bounties; do not
    # guess a cash total by adding dollar amounts found in descriptions.
    prizes = [plain(": ".join(str(p[k]) for k in ("name", "desc") if p.get(k)), 250)
              for p in row.get("prizes", [])]
    host = row.get("hosted_by")
    organizer = host.get("name") if isinstance(host, dict) else host if isinstance(host, str) else None
    mode = "hybrid" if row.get("is_hybrid") else "online" if row.get("is_online") else "in-person"
    return Event(source="devfolio", signals=source_signals("devfolio", row), source_id=str(row["uuid"]), title=plain(row["name"]),
        url=f"https://{slug}.devfolio.co/", description=plain(row.get("tagline") or row.get("desc")),
        image=absolute(row.get("cover_img") or settings.get("logo"), SOURCE["url"]),
        start=start, end=end, registration_deadline=utc(settings.get("reg_ends_at")), format=mode,
        location=None if mode == "online" else plain(row.get("location")) or ", ".join(
            x for x in (row.get("city"), row.get("state"), row.get("country")) if x) or None,
        country=row.get("country") if mode != "online" else None,
        prize="; ".join(p for p in prizes if p)[:500] or None,
        participants=row.get("participants_count"), organizer=plain(organizer),
        tags=list(dict.fromkeys([t["name"] for t in row.get("themes", []) if t.get("name")]
            + [t for t in row.get("hashtags", []) if isinstance(t, str)])),
        kind="hackathon", confidence=0.9, classified_by="source")


def collect() -> list[Event]:
    result, seen = [], set()
    with client() as c:
        check_robots(c, API)
        # 'upcoming' means applications not yet open, NOT all future events.
        # The leading past pages also include currently-running events whose
        # applications have closed. 'past' is newest-first, so stop at the first
        # page where every event has already ended. Filter by actual end date.
        for category in ("application_open", "upcoming", "past"):
            for page in range(MAX_PAGES):
                data = json_response(c.post(API, json={"type": category, "from": page * SIZE, "size": SIZE}))
                hits = data.get("hits", {}).get("hits")
                if not isinstance(hits, list):
                    raise RuntimeError("Devfolio JSON no longer contains hits.hits")
                fresh = False
                for hit in hits:
                    row = hit.get("_source") or {}
                    if row.get("uuid") in seen:
                        continue
                    event = _event(row)
                    if event:
                        fresh = True
                        seen.add(row["uuid"])
                        result.append(event)
                if len(hits) < SIZE or (category == "past" and not fresh):
                    break
            else:
                warn_limit(__name__, category)
    return result
