"""BuilderBase's public cursor-paginated event directory."""
import re
from hackfinder.models import Event
from ._platforms_util import absolute, current, plain, utc
from ._signals_util import count, geo, reward, signals
from ._vertical_util import MAX_PAGES, client, polite_json, robots, warn_limit
from selectolax.lexbor import LexborHTMLParser as HTMLParser

SOURCE = {"id": "builderbase", "name": "BuilderBase", "url": "https://builderbase.com/events",
          "method": "api", "default_kind": "mixed"}
API = "https://edge.builderbase.com/super-events/public/browse"


def _event(r):
    start, end = utc(r.get("start_at")), utc(r.get("end_at"))
    if not r.get("name") or not r.get("slug") or not (start or end) or not current(start, end):
        return None
    loc = r.get("location") or {}
    fmt = {"onsite": "in-person", "online": "online", "hybrid": "hybrid"}.get(r.get("format"), "unknown")
    place = ", ".join(x for x in [loc.get("city"), loc.get("country")] if x)
    participants = count(r.get("participant_count"))
    return Event(source="builderbase", source_id=str(r["id"]), title=plain(r["name"]),
        url=absolute("/event/" + r["slug"], SOURCE["url"]), description=plain(r.get("description")),
        image=absolute(r.get("cover_image_url"), SOURCE["url"]), start=start, end=end,
        registration_deadline=utc(r.get("registration_deadline")), format=fmt,
        location=place or None if fmt != "online" else None, country=loc.get("country") if fmt != "online" else None,
        participants=participants, organizer=(r.get("organization") or {}).get("name"),
        prize=r.get("prize"), signals=signals(text=r.get("description"), registrations=participants,
            **geo(loc.get("lat"), loc.get("lng")), **reward(r.get("prize"))))


def collect():
    events, seen, cursor = {}, set(), None
    with client(timeout=20) as c:
        robots(c, SOURCE["url"])
        for _ in range(MAX_PAGES):
            params = {"status": "all", "limit": 50}
            if cursor:
                params["cursor"] = cursor
            data = polite_json(c, API, params=params).get("data") or {}
            rows = data.get("super_events")
            if not isinstance(rows, list):
                raise RuntimeError("BuilderBase directory no longer returns super_events")
            fresh = [r for r in rows if r["id"] not in seen]
            seen.update(r["id"] for r in fresh)
            for r in fresh:
                if _event(r):
                    detail = polite_json(c, "https://edge.builderbase.com/super-events/public/" + r["slug"])
                    record = (detail.get("data") or {}).get("super_event")
                    if not isinstance(record, dict):
                        raise RuntimeError("BuilderBase public detail has no super_event")
                    merged = {**r, **record}
                    e = _event(merged)
                    if e:
                        tree = HTMLParser((record.get("page_data") or {}).get("html") or "")
                        for node in tree.css("script, style"):
                            node.decompose()
                        text = tree.text(separator=" ")
                        e.description = e.description or plain(text)
                        match = re.search(r"(?:prize pool|total prizes)\s*[:—-]?\s*(?:of\s+)?([$€£₹]\s*[\d,.]+(?:[kKmM]\b)?)", text, re.I)
                        if not e.prize and match:
                            e.prize = match[1]
                            e.signals.update(reward(e.prize.replace("€", "EUR ").replace("£", "GBP ").replace("₹", "INR ")))
                        e.signals.update(signals(text=record.get("description") or text))
                        events[e.url] = e
            next_cursor = data.get("next_cursor")
            if not fresh or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        else:
            warn_limit(__name__)
    return list(events.values())
