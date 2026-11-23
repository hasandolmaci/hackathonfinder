"""Eventornado public AJAX event cards + server-embedded Vue event JSON.
Eventornado itself is the registration platform unless an explicit registration link is supplied.
"""
import json
import re
import time

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from hackfinder.models import Event
from ._country_sites import clean_url
from ._platforms_util import MAX_PAGES, absolute, check_robots, client, current, plain, utc, warn_limit
from ._signals_util import count, reward, signals
from ._vertical_util import polite_json

SOURCE = {"id": "eventornado", "name": "Eventornado", "url": "https://eventornado.com/events",
          "method": "api", "default_kind": "hackathon"}


def parse_list(html):
    rows = []
    for card in HTMLParser(html).css("div.card"):
        a = card.css_first(".event-name a")
        if not a:
            continue
        def text(sel):
            n = card.css_first(sel)
            return plain(n.text()) if n else None
        rows.append({"url": absolute(a.attributes.get("href"), SOURCE["url"]), "title": plain(a.text()),
            "format": {"online": "online", "offline": "in-person", "hybrid": "hybrid"}.get((text(".type-status") or "").lower(), "unknown"),
            "organizer": text(".organization-name"), "prize": text(".prize-pool")})
    return rows


def parse_detail(html):
    for node in HTMLParser(html).css("*"):
        if ":event" in node.attributes:
            data = json.loads(node.attributes[":event"])
            if isinstance(data, dict):
                return data
    raise RuntimeError("Eventornado HTML no longer contains public :event JSON")


def to_event(row, data):
    start, end = utc(data.get("start_date")), utc(data.get("end_date"))
    if not data.get("name") or not (start or end) or not current(start, end) or data.get("deleted_at") or data.get("status") == 2:
        return None
    tabs = data.get("event_info_tabs") or []
    text = " ".join([data.get("description") or "", *[t.get("content") or "" for t in tabs]])
    url = row["url"]
    # Only labelled application/registration links; sponsor and organizer links are not event URLs.
    for a in HTMLParser(text).css("a[href]"):
        link = absolute(a.attributes.get("href"), url)
        if link and re.fullmatch(r"(?:register|apply|registration|apply here|register here)", a.text(strip=True), re.I) and "/mentors/" not in link:
            url = clean_url(link)
            break
    themes = [t["name"] for t in data.get("topics") or [] if t.get("name")]
    sponsors = []
    for tab in tabs:
        if re.search(r"sponsors?|partners?", tab.get("title") or "", re.I):
            sponsors += [plain(a.text()) for a in HTMLParser(tab.get("content") or "").css("a[href]") if plain(a.text())]
    cash = reward(row.get("prize"))
    participants = count(data.get("participants_count"))
    return Event(source="eventornado", source_id=str(data["id"]), url=url, title=plain(data["name"]),
        description=plain(data.get("description")), start=start, end=end, format=row["format"],
        image=absolute(data.get("image"), "https://assets-live.eventornado.com/"),
        organizer=row.get("organizer"), prize=row.get("prize"), participants=participants,
        prize_usd=cash.get("prize_amount") if cash.get("prize_currency") == "USD" else None,
        tags=themes, kind="hackathon", confidence=0.9, classified_by="source",
        signals=signals(text=text, registrations=participants, themes=themes or None,
            sponsors=list(dict.fromkeys(sponsors)) or None, **cash))


def collect():
    events, seen = {}, set()
    with client() as c:
        check_robots(c, SOURCE["url"])
        for status in (0, 1):  # upcoming, ongoing (never traverse the archive)
            for page in range(1, MAX_PAGES + 1):
                time.sleep(1.1)
                data = polite_json(c, SOURCE["url"], params={"page": page, "status": status},
                    headers={"X-Requested-With": "XMLHttpRequest"})
                if "events" not in data or "finished" not in data:
                    raise RuntimeError("Eventornado listing response changed")
                rows = [r for r in parse_list(data.get("events") or "") if r["url"] not in seen]
                for row in rows:
                    seen.add(row["url"])
                    time.sleep(1.1)
                    r = c.get(row["url"], headers={"Accept": "text/html"})
                    r.raise_for_status()
                    if event := to_event(row, parse_detail(r.text)):
                        events[event.source_id] = event
                if not rows or data["finished"]:
                    break
            else:
                warn_limit(__name__, str(status))
    return list(events.values())
