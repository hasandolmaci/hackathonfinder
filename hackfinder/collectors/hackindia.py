"""All HackIndia events embedded in the listing's Next Flight payload (Show more is local)."""
import re
import time
from hackfinder.models import Event
from ._html_util import objects
from ._platforms_util import absolute, current, plain, utc
from ._signals_util import count, flag, reward, signals
from ._vertical_util import client, robots

SOURCE = {"id": "hackindia", "name": "HackIndia", "url": "https://hackindia.org/hackathons",
          "method": "api", "default_kind": "hackathon"}


def _event(r):
    start, end = utc(r.get("start_date")), utc(r.get("end_date"))
    if not r.get("title") or not start or not current(start, end) or r.get("is_cancelled") or r.get("is_draft") or r.get("is_active") == 0:
        return None
    if r.get("status") in ("completed", "cancelled", "ended"):
        return None
    slug = re.sub(r"-+", "-", re.sub(r"\s+", "-", re.sub(r"[^a-z0-9\s-]", "", r["title"].lower()).strip()))
    themes, participants = r.get("tracks") or [], count(r.get("current_participants"))
    return Event(source="hackindia", source_id=str(r["id"]), title=plain(r["title"]),
        url=absolute(f"/{start.year}/{slug}", SOURCE["url"]), start=start, end=end,
        registration_deadline=utc(r.get("registration_end_date")), description=plain(r.get("description")),
        image=absolute(r.get("image_url"), SOURCE["url"]), format="online" if r.get("is_online") else "in-person",
        location=None if r.get("is_online") else r.get("location"), country=None if r.get("is_online") else "India",
        prize=r.get("prize_pool"), participants=participants, organizer="HackIndia", tags=themes,
        signals=signals(text=r.get("description"), registrations=participants, themes=themes,
            featured=flag(r.get("is_featured")), **reward((r.get("prize_pool") or "").replace("₹", "INR "))),
        kind="hackathon", confidence=0.9, classified_by="source")


def parse(html):
    block = next((r for r in objects(html) if isinstance(r.get("initialEvents"), list)), None)
    if block is None:
        raise RuntimeError("HackIndia listing has no initialEvents")
    return [e for r in block["initialEvents"] if (e := _event(r))]


def collect():
    with client(timeout=20) as c:
        robots(c, SOURCE["url"])
        time.sleep(1.1)
        r = c.get(SOURCE["url"])
        r.raise_for_status()
        return parse(r.text)
