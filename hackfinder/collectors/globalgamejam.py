"""Global Game Jam: the current year's jam-site list (/jam-sites/<year>?page=N, 50 sites per page).

Cloudflare answers plain HTTP with 403 but its automatic JS challenge passes in a real browser,
so everything goes through cdp_page: the home page supplies the jam dates ("Jam Dates 25 - 31
January 2027") and clears the challenge, then each list page is fetched from inside that page.
Each site is one event (a physical or online location); the Jam Site Type filter (In-Person /
Online / Hybrid) is crawled too so every site gets a format. Pages stop at the first empty one.
"""
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from hackfinder.browser import cdp_page
from hackfinder.models import Event
from ._signals_util import source_signals
from ._vertical_util import MAX_PAGES, browser_worker, check_block, client, plain, robots, warn_limit

SOURCE = {"id": "globalgamejam", "name": "Global Game Jam", "url": "https://globalgamejam.org/jam-sites",
          "method": "scrape", "default_kind": "game_jam"}
BASE = "https://globalgamejam.org"
TYPES = {"170": "online", "171": "in-person", "172": "hybrid"}  # field_jam_site_type_target_id
DATES = re.compile(r"Jam Dates\s*(\d{1,2})\s*(?:([A-Za-z]+))?\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})")


def jam_dates(text: str):
    """'Jam Dates 25 - 31 January 2027' -> (start, end) UTC, else (None, None). Pure."""
    m = DATES.search(text or "")
    if not m:
        return None, None
    try:
        end = datetime.strptime(f"{m[3]} {m[4][:3]} {m[5]}", "%d %b %Y").replace(tzinfo=timezone.utc)
        start = datetime.strptime(f"{m[1]} {(m[2] or m[4])[:3]} {m[5]}", "%d %b %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None, None
    return start, end


def parse(html: str, year: int, start=None, end=None, fmt: str = "unknown") -> list[Event]:
    """One list page -> one Event per jam-site card (pure; testable offline)."""
    events = []
    for card in HTMLParser(html).css("div.group--jam-site"):
        link = card.css_first("a.cta")
        if not link or not link.attributes.get("href"):
            continue
        address = plain(card.css_first("span.address").text()) if card.css_first("span.address") else None
        flag = card.css_first("span.address i")
        code = (flag.attributes.get("class") or "").partition("flag:")[2].strip() if flag else ""
        image = card.css_first("img")
        src = image.attributes.get("src") if image else None
        url = urljoin(BASE, link.attributes["href"])
        events.append(Event(
            source="globalgamejam", signals=source_signals("globalgamejam", {}), source_id=url.rstrip("/").rpartition("/")[2], url=url, title=plain(link.text()),
            description=f"Global Game Jam {year} jam site" + (f" in {address}" if address else "") + ".",
            image=urljoin(BASE, src) if src and "default.png" not in src else None,
            start=start, end=end, format=fmt, location=None if fmt == "online" else address,
            country=address.rsplit(",", 1)[-1].strip() if address and "," in address else code or None,
            tags=["game jam", f"ggj{year}"], kind="game_jam", confidence=0.9, classified_by="source"))
    return events


def collect() -> list[Event]:
    with client() as c:
        robots(c, SOURCE["url"])
    return browser_worker("globalgamejam")


def _pages(page, year, params, seen):
    """Fetch /jam-sites/<year>?page=N from inside the challenge-cleared page until an empty page."""
    for n in range(MAX_PAGES):
        query = f"page={n}" + (f"&{params}" if params else "")
        html = page.evaluate("u => fetch(u, {credentials: 'same-origin'}).then(r => r.status === 200 ? r.text() : '')",
                             f"{BASE}/jam-sites/{year}?{query}")
        cards = HTMLParser(html).css("div.group--jam-site")
        fresh = [x for x in cards if x.css_first("a.cta") and x.css_first("a.cta").attributes.get("href") not in seen]
        if not cards or not fresh:
            return
        seen.update(x.css_first("a.cta").attributes["href"] for x in fresh)
        yield html
    warn_limit(__name__, f"{year} {params}")


def _collect():
    with cdp_page() as page:
        resp = page.goto(BASE + "/", wait_until="domcontentloaded", timeout=30000)
        try:  # an automatic Cloudflare check can take a while to clear by itself
            page.wait_for_selector("main", timeout=40000)
        except Exception:
            check_block(page)
            raise RuntimeError(f"no page content at {page.url} (HTTP {resp.status if resp else '?'}, "
                               f"title {page.title()!r})") from None
        check_block(page)
        text = page.locator("main").inner_text(timeout=5000)
        start, end = jam_dates(re.sub(r"\s+", " ", text or ""))
        if not end:
            raise RuntimeError("Global Game Jam home page shows no jam dates; markup may have changed")
        if end.date() < datetime.now(timezone.utc).date():
            return []  # this year's jam is over and the next is not announced yet
        year = end.year
        formats, events = {}, {}
        for tid, fmt in TYPES.items():
            seen = set()
            for _ in _pages(page, year, f"field_jam_site_type_target_id={tid}", seen):
                pass  # the pages only fill `seen`
            formats.update({href: fmt for href in seen})
        seen = set()
        for html in _pages(page, year, "", seen):
            for e in parse(html, year, start, end):
                events[e.url] = e
        for e in events.values():
            fmt = formats.get("/jam-sites/%d/%s" % (year, e.source_id), "unknown")
            e.format = fmt
            e.location = None if fmt == "online" else e.location
        if not events:
            raise RuntimeError("Global Game Jam list returned no sites; markup may have changed")
    return list(events.values())
