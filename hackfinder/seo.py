"""Search-engine side of the site: page metadata, landing pages, server-rendered listing rows, robots.txt and sitemap.

Pages are still the static HTML files; this module fills in what a crawler needs before any JavaScript runs:
title, description, canonical URL, social previews, the first page of events and plain links to the next pages.
Set HF_SITE_URL (e.g. https://hackfinder.eu) so canonical URLs point at the real domain, not a preview host.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
import json
import os

SITE_NAME = "Hackfinder"
TAGLINE = "Find hackathons, game jams and buildathons"
PER_PAGE = 25
MIN_EVENTS = 5  # landing pages with fewer upcoming events are kept out of the index and the sitemap

# slug -> (heading, phrase used in sentences, API filters). Curated on purpose: a page only exists when it is useful
# on its own, never as an automatic combination of every filter.
LANDINGS: dict[str, tuple[str, str, dict]] = {
    "online": ("Online hackathons", "online hackathons you can join from anywhere", {"format": "online"}),
    "europe": ("Hackathons in Europe", "upcoming hackathons in Europe", {"regions": ("europe",)}),
    "north-america": ("Hackathons in North America", "upcoming hackathons in North America", {"regions": ("north_america",)}),
    "asia": ("Hackathons in Asia", "upcoming hackathons in Asia", {"regions": ("asia",)}),
    "netherlands": ("Hackathons in the Netherlands", "upcoming hackathons in the Netherlands", {"countries": ("NL",)}),
    "germany": ("Hackathons in Germany", "upcoming hackathons in Germany", {"countries": ("DE",)}),
    "united-kingdom": ("Hackathons in the United Kingdom", "upcoming hackathons in the UK", {"countries": ("GB",)}),
    "france": ("Hackathons in France", "upcoming hackathons in France", {"countries": ("FR",)}),
    "united-states": ("Hackathons in the United States", "upcoming hackathons in the US", {"countries": ("US",)}),
    "canada": ("Hackathons in Canada", "upcoming hackathons in Canada", {"countries": ("CA",)}),
    "india": ("Hackathons in India", "upcoming hackathons in India", {"countries": ("IN",)}),
    "ai": ("AI hackathons", "upcoming AI and machine learning hackathons", {"categories": ("ai",)}),
    "web3": ("Web3 and crypto hackathons", "upcoming Web3 and crypto hackathons", {"categories": ("web3",)}),
    "fintech": ("Fintech hackathons", "upcoming fintech hackathons", {"categories": ("fintech",)}),
    "health": ("Health and biotech hackathons", "upcoming health and biotech hackathons", {"categories": ("health",)}),
    "climate": ("Climate hackathons", "upcoming climate and sustainability hackathons", {"categories": ("climate",)}),
    "game-jams": ("Game jams", "upcoming game jams", {"kinds": ("game_jam",)}),
}

# Same filters expressed as the URL parameters list.js reads, so the interactive table starts where the page did.
def preset(filters: dict) -> dict:
    keys = {"format": "format", "regions": "region", "countries": "country", "categories": "categories", "kinds": "kinds"}
    return {keys[k]: v if isinstance(v, str) else ",".join(v) for k, v in filters.items()}


def site_url(request_base: str) -> str:
    base = (os.getenv("HF_SITE_URL") or request_base).rstrip("/")
    local = any(h in base for h in ("://localhost", "://127.0.0.1", "://testserver"))
    return base if local else base.replace("http://", "https://", 1)  # behind Vercel's proxy the app sees http


def head(title: str, description: str, url: str, extra: str = "", noindex: bool = False) -> str:
    t, d, u = escape(title), escape(description), escape(url)
    tags = [f"<title>{t}</title>", f'<meta name="description" content="{d}">', f'<link rel="canonical" href="{u}">',
            f'<meta property="og:type" content="website"><meta property="og:site_name" content="{SITE_NAME}">',
            f'<meta property="og:title" content="{t}"><meta property="og:description" content="{d}">',
            f'<meta property="og:url" content="{u}"><meta name="twitter:card" content="summary">',
            f'<meta name="twitter:title" content="{t}"><meta name="twitter:description" content="{d}">']
    if noindex:
        tags.append('<meta name="robots" content="noindex,follow">')
    return "".join(tags) + extra


def json_ld(data: dict) -> str:
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def with_head(html: str, tags: str) -> str:
    start, end = html.index("<title>"), html.index("</title>") + len("</title>")
    return html[:start] + tags + html[end:]


def _date(value: str | None) -> str:
    if not value:
        return "Date to be announced"
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return f"{d:%b} {d.day}, {d.year}"
    except ValueError:
        return "Date to be announced"


def _number(value) -> str:
    return f"{value:,}" if isinstance(value, int) else "—"


FORMATS = {"online": "Online", "in-person": "In person", "hybrid": "Hybrid"}
KINDS = {"hackathon": "Hackathon", "game_jam": "Game jam", "ctf": "CTF", "coding_competition": "Coding competition",
         "ideathon": "Ideathon"}


def rows(events: list[dict]) -> str:
    """Plain table rows with the same columns as the interactive table; list.js replaces them once it has loaded."""
    out = []
    for e in events:
        location = e.get("location") or ("Worldwide" if e.get("format") == "online" else "—")
        score = e.get("score")
        out.append(
            f'<tr data-ssr><td></td><td><a class="event-title" href="{escape(e["url"])}" rel="noopener">{escape(e["title"])}</a></td>'
            f'<td>{score if score is not None else "—"}</td><td>{escape(KINDS.get(e.get("kind"), e.get("kind") or ""))}</td>'
            f'<td><span class="format-chip {escape(e.get("format") or "")}">{escape(FORMATS.get(e.get("format"), "Unknown"))}</span></td>'
            f'<td>{escape(_date(e.get("start")))}</td><td>{escape(location)}</td><td>{_number(e.get("participants"))}</td>'
            f'<td class="prize">{escape(e.get("prize") or "—")}</td></tr>')
    return "".join(out)


def pages_nav(path: str, page: int, total: int) -> str:
    last = max(1, -(-total // PER_PAGE))
    if last == 1:
        return ""
    links = []
    if page > 1:
        links.append(f'<a href="{path}{"" if page == 2 else f"?page={page - 1}"}" rel="prev">Previous page</a>')
    links.append(f"<span>Page {page} of {last}</span>")
    if page < last:
        links.append(f'<a href="{path}?page={page + 1}" rel="next">Next page</a>')
    return '<nav id="ssr-pages" class="ssr-pages" aria-label="Pages">' + " ".join(links) + "</nav>"


def top_places(events: list[dict], limit: int = 3) -> list[str]:
    counts: dict[str, int] = {}
    for e in events:
        if e.get("format") == "online" or not e.get("location"):
            continue
        city = e["location"].split(",")[0].strip()
        if city and len(city) < 40:
            counts[city] = counts.get(city, 0) + 1
    return [c for c, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:limit]]


def intro(phrase: str, total: int, events: list[dict]) -> str:
    places = top_places(events)
    where = ""
    if len(places) >= 2:
        where = f", including events in {', '.join(places[:-1])} and {places[-1]}"
    count = f"{total:,} {phrase}" if total != 1 else f"1 of the {phrase}"
    return (f"{count}{where}. Listings are collected from organizer pages and refreshed several times a day; "
            "open an event to register on its own site.")


def browse_links(counts: dict[str, int], current: str | None = None) -> str:
    links = [f'<a href="/hackathons/{slug}"{" aria-current=page" if slug == current else ""}>{escape(LANDINGS[slug][0])}</a>'
             for slug in LANDINGS if counts.get(slug, 0) >= MIN_EVENTS]
    if not links:
        return ""
    return ('<nav class="browse-links" aria-labelledby="browse-heading"><h2 id="browse-heading" class="mono">BROWSE HACKATHONS</h2>'
            + "".join(links) + "</nav>")


def robots(base: str) -> str:
    return f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {base}/sitemap.xml\n"


def sitemap(base: str, paths: list[tuple[str, str | None]]) -> str:
    items = []
    for path, lastmod in paths:
        mod = f"<lastmod>{escape(lastmod[:10])}</lastmod>" if lastmod else ""
        items.append(f"<url><loc>{escape(base + path)}</loc>{mod}</url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(items) + "</urlset>\n")
