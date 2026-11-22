"""WeMakeDevs hackathon cards from the Next.js payload of the rendered listing (online/in-person, India and global)."""
import json
import re

from hackfinder.browser import cdp_page
from hackfinder.models import Event
from ._signals_util import source_signals
from ._vertical_util import browser_worker, check_block, client, dt, plain, robots, upcoming

SOURCE = {"id": "wemakedevs", "name": "WeMakeDevs", "url": "https://www.wemakedevs.org/hackathons",
          "method": "scrape", "default_kind": "hackathon"}
FORMATS = {"online": "online", "offline": "in-person", "hybrid": "hybrid"}


def collect() -> list[Event]:
    with client() as c:
        robots(c, SOURCE["url"])
    return browser_worker("wemakedevs")


def _cards(html):
    """Decode the card list embedded in the Next.js flight data."""
    for chunk in re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, flags=re.S):
        text = json.loads(f'"{chunk}"')
        i = text.find('"cards":[{')
        if i < 0:
            continue
        cards, _ = json.JSONDecoder().raw_decode(text[i + len('"cards":'):])
        return cards
    return []


def _event(card):
    start, end = dt(card.get("startDate")), dt(card.get("endDate"))
    if not card.get("title") or not card.get("href") or not upcoming(start, end):
        return None
    url = card["href"] if card["href"].startswith("http") else "https://www.wemakedevs.org" + card["href"]
    formats = card.get("formats") or []
    fmt = "hybrid" if "hybrid" in formats or len(set(formats)) > 1 else FORMATS.get(formats[0] if formats else "", "unknown")
    prize = plain((card.get("prize") or "").replace("$$", "$")) or None
    amount = re.match(r"\$\s?([\d,]+(?:\.\d+)?)", prize or "")
    place = (card.get("location") or "").strip()
    return Event(source="wemakedevs", signals=source_signals("wemakedevs", card), source_id=str(card.get("id") or card.get("hackathonSlug") or ""),
        url=url, title=plain(card["title"]), description=prize, image=card.get("image"), start=start, end=end,
        format=fmt, location=None if fmt == "online" or place.lower() == "remote" else place or None,
        prize=prize, prize_usd=float(amount[1].replace(",", "")) if amount else None, organizer="WeMakeDevs",
        tags=[card["seriesSlug"]] if card.get("seriesSlug") else [], kind="hackathon", confidence=0.9, classified_by="source")


def _collect():
    with cdp_page() as page:
        page.goto(SOURCE["url"], wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('a[href^="/hackathons/"]', timeout=15000)
        check_block(page)
        cards = _cards(page.content())
    if not cards:
        raise RuntimeError("WeMakeDevs hackathon cards not found; the page payload may have changed")
    events = {}
    for card in cards:
        event = _event(card)
        if event:
            events[event.url] = event
    return sorted(events.values(), key=lambda e: (e.start is None, e.start))
