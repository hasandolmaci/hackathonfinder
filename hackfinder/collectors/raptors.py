"""Raptors' event directory and original event sites, using public JSON-LD."""
import re
import time
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from ._html_util import objects
from ._platforms_util import absolute, current, plain
from ._signals_util import count, geo, names, reward, signals
from ._vertical_util import client, robots, schema_event

SOURCE = {"id": "raptors", "name": "Hackathon Raptors", "url": "https://www.raptors.dev/",
          "method": "api", "default_kind": "mixed"}


def listing(html):
    rows = next((r for r in objects(html) if r.get("@type") == "ItemList" and r.get("@id", "").endswith("#events")), None)
    if rows is None:
        raise RuntimeError("Raptors directory has no events ItemList")
    return list(dict.fromkeys(u for r in rows.get("itemListElement", []) if (u := absolute(r.get("url"), SOURCE["url"]))))


def parse(html, base):
    rows, events = list(objects(html)), {}
    orgs = {r["@id"]: r.get("name") for r in rows if r.get("@type") == "Organization" and r.get("@id")}
    for raw in rows:
        typ = raw.get("@type", "")
        if not any("Event" in str(t) or t == "Hackathon" for t in (typ if isinstance(typ, list) else [typ])):
            continue
        r = dict(raw)
        if typ == "Hackathon":
            r["@type"] = "Event"
        kind = "hackathon" if typ == "Hackathon" else "unknown"
        e = schema_event(r, "raptors", base, kind)
        if not e or not (e.start or e.end) or not current(e.start, e.end):
            continue
        org = r.get("organizer") or {}
        if isinstance(org, dict):
            e.organizer = org.get("name") or orgs.get(org.get("@id")) or "Hackathon Raptors"
        loc = r.get("location") or {}
        loc = loc if isinstance(loc, dict) else {}
        coordinates = loc.get("geo") or {}
        prize = r.get("prize") or r.get("prizePool")
        if not prize:
            # Read explicit total-prize copy, never add individual awards together.
            text = HTMLParser(html)
            for n in text.css('script, style'):
                n.decompose()
            body = text.text(separator=" ")
            m = re.search(r"(?:\$[\d,]+(?:\.\d+)?\s+(?:in\s+)?(?:cash\s+)?prizes|(?:total prize pool|prize pool|total prizes)\s*[:—-]?\s*\$[\d,]+)", body, re.I)
            prize = m[0] if m else None
        participants = count((r.get("interactionStatistic") or {}).get("userInteractionCount")) if isinstance(r.get("interactionStatistic"), dict) else None
        themes = names(r.get("about")) if isinstance(r.get("about"), list) else None
        e.prize, e.participants = plain(prize), participants
        e.signals = signals(text=r.get("description"), registrations=participants, themes=themes,
            sponsors=names(r["sponsor"] if isinstance(r["sponsor"], list) else [r["sponsor"]]) if r.get("sponsor") else None,
            **geo(coordinates.get("latitude"), coordinates.get("longitude")), **reward(prize))
        events[e.url] = e
    return list(events.values())


def collect():
    events, errors = {}, []
    with client(timeout=20) as c:
        robots(c, SOURCE["url"])
        time.sleep(1.1)
        r = c.get(SOURCE["url"])
        r.raise_for_status()
        for url in listing(r.text):
            time.sleep(1.1)
            try:
                robots(c, url)
                time.sleep(1.1)
                r = c.get(url)
                r.raise_for_status()
                for e in parse(r.text, str(r.url)):
                    events[e.url] = e
            except Exception as exc:
                errors.append(f"{url}: {exc}")
    if errors:
        # A failed original event site must not silently masquerade as complete coverage.
        import logging
        logging.getLogger(__name__).warning("Raptors detail failures: %s", "; ".join(errors))
        if not events:
            raise RuntimeError("; ".join(errors))
    return list(events.values())
