"""Country hackathon network: public RSS + sitemap + schema.org Event pages.
Original offers URLs are used for dedupe; /go/ and /api/ are never requested.
"""
from __future__ import annotations

import json
import re
import time
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from hackfinder.models import Event
from ._platforms_util import MAX_PAGES, absolute, check_robots, client, current, number, plain, utc, warn_limit
from ._signals_util import count, geo, names, reward, signals
from ._vertical_util import walk

COUNTRIES = {"NL": "Netherlands", "DE": "Germany", "GB": "United Kingdom", "UK": "United Kingdom",
    "FR": "France", "ES": "Spain", "JP": "Japan", "TR": "Turkey", "AU": "Australia", "CA": "Canada",
    "US": "United States", "SG": "Singapore", "MX": "Mexico", "SE": "Sweden", "IT": "Italy",
    "VN": "Vietnam", "HK": "Hong Kong", "AR": "Argentina", "CO": "Colombia", "PK": "Pakistan",
    "AT": "Austria", "ID": "Indonesia", "IN": "India", "KR": "South Korea", "TW": "Taiwan",
    "TH": "Thailand", "NZ": "New Zealand"}


def event_urls(*documents, base="https://netherlandshackathons.com"):
    """Native-language event URLs in RSS/sitemap, in source order. Pure."""
    found = re.findall(r"<(?:loc|link)>\s*([^<\s]+)\s*</(?:loc|link)>", "\n".join(documents))
    host = urlsplit(base).netloc
    return list(dict.fromkeys(unescape(u) for u in found if urlsplit(u).netloc == host
                             and re.fullmatch(r"/events/[^/]+/?", urlsplit(u).path)))


def parse_event(html):
    for script in HTMLParser(html).css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
        except ValueError:
            continue
        for node in walk(data):
            kinds = node.get("@type", [])
            if "Event" in ([kinds] if isinstance(kinds, str) else kinds):
                return node
    return None


def clean_url(url):
    if not url:
        return None
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")])
    return parts._replace(query=query).geturl()


def to_event(node, page_url, source="netherlandshackathons", country="Netherlands", html=""):
    start, end = utc(node.get("startDate")), utc(node.get("endDate"))
    if not node.get("name") or not (start or end) or not current(start, end):
        return None
    if any(s in str(node.get("eventStatus", "")) for s in ("Cancelled", "Postponed")):
        return None
    offers = node.get("offers") or []
    offers = [offers] if isinstance(offers, dict) else offers
    offers = [o for o in offers if isinstance(o, dict)]
    org = node.get("organizer") or {}
    org = org[0] if isinstance(org, list) and org else org
    org = org if isinstance(org, dict) else {}
    link = next((o["url"] for o in offers if o.get("url")), None) or org.get("url")
    url = clean_url(absolute(link, page_url)) or page_url
    if urlsplit(url).netloc == urlsplit(page_url).netloc and urlsplit(url).path.startswith(("/go/", "/api/")):
        url = page_url
    loc = node.get("location") or {}
    loc = loc[0] if isinstance(loc, list) and loc else loc
    loc = loc if isinstance(loc, dict) else {}
    addr = loc.get("address") or {}
    addr = addr if isinstance(addr, dict) else {"streetAddress": addr}
    code = addr.get("addressCountry")
    code = code.get("name") if isinstance(code, dict) else code
    country = COUNTRIES.get(code, code) or country
    mode = str(node.get("eventAttendanceMode", ""))
    fmt = "hybrid" if "Mixed" in mode else "online" if "Online" in mode or loc.get("@type") == "VirtualLocation" else "in-person" if loc or "Offline" in mode else "unknown"
    location = None if fmt == "online" else ", ".join(x for x in (addr.get("addressLocality"), country) if x) or plain(loc.get("name"))
    prices = [v for o in offers if (v := number(o.get("price"))) is not None]
    paid = max(prices) > 0 if prices else False if node.get("isAccessibleForFree") is True else None
    cur = next((o.get("priceCurrency") for o in offers if o.get("priceCurrency")), None)
    tree = HTMLParser(html)
    body = tree.css_first("main .prose, main .event-description, main .about-content")
    text = body.text() if body else " ".join(n.text() for n in tree.css("main p.body-p")) or node.get("description")
    tags = list(dict.fromkeys(a.text(strip=True).lstrip("#") for a in tree.css("main .tag")))
    prize_node = tree.css_first("main .prize, main .info-strip .chip-val.gold")
    prize = plain(prize_node.text()) if prize_node else plain(node.get("award"))
    cash = reward(prize)
    participants = count(node.get("attendeeCount"))
    # Headline counts and map coordinates are published in the rendered HTML.
    hit = re.search(r"(\d[\d,]*)\s+(?:registered|registrations|angemeldet|inscrits|inscritos)", tree.text(), re.I)
    if participants is None and hit:
        participants = count(hit[1])
    coord = loc.get("geo") or {}
    coords = geo(coord.get("latitude"), coord.get("longitude")) if isinstance(coord, dict) else {}
    if not coords:
        hit = re.search(r"[?&]query=(-?\d+\.\d+),(-?\d+\.\d+)", unescape(html))
        if hit:
            coords = geo(hit[1], hit[2])
    title = plain(node["name"], 300)
    jam = bool(re.search(r"\bgame\s*jam\b", title + " " + (node.get("description") or "")[:200], re.I))
    image = node.get("image")
    image = image[0] if isinstance(image, list) and image else image
    return Event(source=source, source_id=page_url.rstrip("/").split("/")[-1], url=url, title=title,
        description=plain(node.get("description")), image=absolute(image, page_url) if isinstance(image, str) else None,
        start=start, end=end, registration_deadline=utc(node.get("registrationDeadline")), format=fmt,
        location=location, country=country, organizer=plain(org.get("name"), 200), prize=prize,
        prize_usd=cash.get("prize_amount") if cash.get("prize_currency") == "USD" else None,
        participants=participants, tags=tags, kind="game_jam" if jam else "hackathon", confidence=0.9, classified_by="source",
        signals=signals(text=text, paid_entry=paid, registrations=participants, themes=tags or None,
            sponsors=names(node["sponsor"] if isinstance(node["sponsor"], list) else [node["sponsor"]]) if node.get("sponsor") else None,
            entry_fee=f"{min(prices):g}-{max(prices):g} {cur or ''}".strip() if paid and prices else None,
            hosts=[org["name"]] if org.get("name") else None, registration_url=url if url != page_url else None,
            **cash, **coords))


def collect_site(source, country):
    base, events = source["url"].rstrip("/"), {}
    with client() as c:
        delay = max(1.0, check_robots(c, base + "/"))
        def get(url):
            time.sleep(delay)
            r = c.get(url, headers={"Accept": "text/html, application/xml"})
            if r.status_code in (401, 403, 429):
                raise RuntimeError(f"blocked: HTTP {r.status_code} from {r.url}")
            r.raise_for_status()
            return r.text
        docs = [get(base + "/rss.xml")]
        pending, visited = [base + "/sitemap.xml"], set()
        while pending and len(visited) < MAX_PAGES:
            url = pending.pop(0)
            if url in visited:
                continue
            visited.add(url)
            doc = get(url)
            docs.append(doc)
            if "<sitemapindex" in doc:
                pending.extend(u for u in re.findall(r"<loc>\s*([^<]+)</loc>", doc)
                               if urlsplit(u).netloc == urlsplit(base).netloc and u not in visited)
        if pending:
            warn_limit(source["id"], "sitemap")
        for page in event_urls(*docs, base=base):
            html = get(page)
            node = parse_event(html)
            if not node:
                raise RuntimeError(f"Event JSON-LD missing from {page}")
            if event := to_event(node, page, source["id"], country, html):
                events[event.source_id] = event
    return list(events.values())
