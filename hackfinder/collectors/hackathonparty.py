"""HackathonParty server-rendered /find and JSON-LD inside React flight chunks.
The platform's event page is the original registration URL; organizer homepages are not registrations.
"""
import json
import re
import time

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from ._country_sites import COUNTRIES, parse_event, to_event as schema_event
from ._platforms_util import MAX_PAGES, absolute, check_robots, client, plain, warn_limit
from ._signals_util import reward
from ._vertical_util import walk

SOURCE = {"id": "hackathonparty", "name": "HackathonParty", "url": "https://www.hackathonparty.com/find",
          "method": "api", "default_kind": "hackathon"}


def parse_list(html):
    tree = HTMLParser(html)
    if "Upcoming Hackathons" not in tree.text():
        raise RuntimeError("HackathonParty listing markup changed")
    return list(dict.fromkeys(absolute(a.attributes["href"], SOURCE["url"]) for a in tree.css('a[href^="/hackathons/"]')
        if re.fullmatch(r"/hackathons/\d+", a.attributes["href"]) and not re.match(r"^Ended", a.text(strip=True))))


def parse_detail(html):
    if node := parse_event(html):
        return node
    chunks = []
    for m in re.finditer(r"self\.__next_f\.push\((.*?)\)</script>", html, re.S):
        try:
            row = json.loads(m[1])
            if row[0] == 1 and isinstance(row[1], str):
                chunks.append(row[1])
        except (ValueError, IndexError):
            continue
    # Decode the __html string as JSON, never evaluate JavaScript/React code.
    for m in re.finditer(r'"__html":', "".join(chunks)):
        try:
            encoded, _ = json.JSONDecoder().raw_decode("".join(chunks)[m.end():].lstrip())
            for node in walk(json.loads(encoded)):
                if node.get("@type") == "Event":
                    return node
        except (ValueError, TypeError):
            continue
    raise RuntimeError("HackathonParty event JSON-LD missing")


def to_event(node, page):
    node = dict(node)
    # Unlike country aggregators, this platform owns registration. Its org URL is a homepage.
    org = node.get("organizer") or {}
    node["organizer"] = {k: v for k, v in org.items() if k != "url"}
    event = schema_event(node, page, "hackathonparty", None)
    if event:
        loc = node.get("location") or {}
        if not loc.get("address") and event.format != "online":
            event.location = plain(loc.get("name"))
            tail = (event.location or "").rsplit(",", 1)[-1].strip()
            if tail in COUNTRIES.values():
                event.country = tail
        if re.search(r"prize", node.get("description") or "", re.I):
            cash = reward(node["description"])
            if cash:
                event.signals.update(cash)
                event.prize = f"{cash['prize_amount']:g} {cash['prize_currency']}"
                event.prize_usd = cash["prize_amount"] if cash["prize_currency"] == "USD" else None
    return event


def collect():
    events, seen, visited = {}, set(), set()
    with client() as c:
        check_robots(c, SOURCE["url"])
        url = SOURCE["url"]
        for _ in range(MAX_PAGES):
            if url in visited:
                break
            visited.add(url)
            time.sleep(1.1)
            r = c.get(url, headers={"Accept": "text/html"})
            r.raise_for_status()
            rows = parse_list(r.text)
            for page in rows:
                if page in seen:
                    continue
                seen.add(page)
                time.sleep(1.1)
                d = c.get(page, headers={"Accept": "text/html"})
                d.raise_for_status()
                if event := to_event(parse_detail(d.text), page):
                    events[event.source_id] = event
            nxt = HTMLParser(r.text).css_first('a[rel="next"]')
            if not nxt:
                break
            url = absolute(nxt.attributes.get("href"), url)
            if not url:
                break
        else:
            warn_limit(__name__)
    return list(events.values())
