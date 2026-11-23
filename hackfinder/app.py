"""Read-only FastAPI app: JSON endpoints over the database, and the static frontend.

Nothing here crawls. The worker (hackfinder/worker.py) fills the database; this module
must not import collectors or any scraping library, so the Vercel bundle stays small.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
import json
import os
import math
import unicodedata
from pathlib import Path
import threading
import time

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db, seo
from .categories import CATEGORIES, NEW_DAYS, SPONSORS, TYPES, categorize, flags, sponsors as find_sponsors, unpack
from .regions import COUNTRIES, REGIONS, country_name, resolve

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
CACHE_SECONDS = float(os.getenv("HF_API_CACHE_SECONDS", "30"))
CDN_CACHE = "public, s-maxage=60, stale-while-revalidate=300"
HIDDEN_KINDS = {"other", "unknown"}
# Never sent to the browser: the listing renders none of these, and they are either copyrighted (description),
# personal data (organizer), or raw scraped internals (signals).
_PRIVATE_FIELDS = ("description", "organizer", "signals")

app = FastAPI(title="Hackfinder")

_cache: dict[tuple, tuple[float, object]] = {}
_cache_lock = threading.Lock()
_ready = False


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def clear_cache():
    with _cache_lock:
        _cache.clear()


def _cached(key: tuple, compute):
    """30 s in-process cache; the CDN header covers everything across instances."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    global _ready
    if not _ready and db.backend() == "sqlite":
        db.init()  # local dev only; on Postgres the worker owns the schema
        _ready = True
    value = compute()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def _source_rows() -> list[dict]:
    with db.connect() as conn:
        rows = conn.fetchall("SELECT * FROM sources ORDER BY id")
        counts = {r["source"]: int(r["n"]) for r in conn.fetchall(
            "SELECT source, COUNT(*) AS n FROM event_sources WHERE active = TRUE GROUP BY source")}
    result = []
    for row in rows:
        status = "never" if not row["last_run_at"] else "error" if row["last_error"] else "ok"
        result.append({"id": row["id"], "name": row["name"], "method": row["method"], "status": status,
                       "count": counts.get(row["id"], 0), "last_success_at": row["last_success_at"],
                       "last_run_at": row["last_run_at"], "duration_ms": row["last_duration_ms"],
                       "error": row["last_error"]})
    return result


def _updated_at(sources: list[dict]) -> str | None:
    return max((s["last_success_at"] for s in sources if s["last_success_at"]), default=None)


def _upcoming_where(now: datetime, kinds: list[str]) -> tuple[str, list]:
    cutoff = _iso(now.replace(hour=0, minute=0, second=0, microsecond=0))
    marks = ", ".join("?" for _ in kinds) or "NULL"
    sql = (f"status = 'active' AND kind IN ({marks}) "
           "AND (COALESCE(end_at, start_at) IS NULL OR COALESCE(end_at, start_at) >= ?)")
    return sql, [*kinds, cutoff]


def _like(text: str) -> str:
    escaped = text.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _ids(value: str | None, allowed: dict) -> tuple:
    """Comma-separated ids, unknown ones dropped, sorted so cache keys are stable."""
    return tuple(sorted({v.strip() for v in (value or "").split(",") if v.strip() in allowed}))


def _has(column: str, value: str) -> str:
    return f"{column} LIKE '%,{value},%'"  # value is a validated taxonomy id, never user text


def _new_cutoff(now: datetime) -> str:
    return _iso(now - timedelta(days=NEW_DAYS))


def _taxonomy(row: dict, now: datetime) -> tuple[list, list]:
    """Categories and flags from the indexed columns (computed on the fly before the first rescore)."""
    if row.get("cats") is None or row.get("flags") is None:
        from .models import Event
        event = Event.model_validate(db.loads(row["data"]))
        cats, found = categorize(event), flags(event)
    else:
        cats, found = unpack(row["cats"]), unpack(row["flags"])
    if row["first_seen"] >= _new_cutoff(now):
        found = [*found, "new"]
    return cats, found


def _sponsors(row: dict) -> list[str]:
    """Sponsor brand ids from the indexed column (computed on the fly before the first rescore)."""
    if row.get("sponsors") is None:
        from .models import Event
        return find_sponsors(Event.model_validate(db.loads(row["data"])))
    return unpack(row["sponsors"])


def _place(row: dict) -> tuple[str | None, str | None]:
    """(country_code, region) from the indexed columns (computed on the fly before the first rescore)."""
    if row.get("region") is None and row.get("country_code") is None:
        from .models import Event
        return resolve(Event.model_validate(db.loads(row["data"])), use_geo=False)
    return row["country_code"], row["region"]


def _foryou(row: dict, interests: tuple) -> float:
    hits = sum(1 for i in interests if f",{i}," in (row["cats"] or ","))
    return (45 if row["score"] is None else row["score"]) + 12 * min(hits, 2)


def _listing(kinds: tuple, format: str | None, q: str, days: str, sort: str, order: str,
             page: int, per_page: int, min_score=None, lat=None, lon=None, radius_km=100,
             categories: tuple = (), types: tuple = (), interests: tuple = (),
             regions: tuple = (), countries: tuple = (), brands: tuple = ()) -> dict:
    now = utcnow()
    where, params = _upcoming_where(now, list(kinds))
    if brands:  # any of the chosen sponsors
        where += " AND (" + " OR ".join(_has("sponsors", b) for b in brands) + ")"
    if categories:
        where += " AND (" + " OR ".join(_has("cats", c) for c in categories) + ")"
    for kind_flag in types:
        if kind_flag == "new":
            where += " AND first_seen >= ?"
            params.append(_new_cutoff(now))
        else:
            where += " AND " + _has("flags", kind_flag)
    if regions:
        where += f" AND region IN ({', '.join('?' for _ in regions)})"
        params.extend(regions)
    if countries:
        where += f" AND country_code IN ({', '.join('?' for _ in countries)})"
        params.extend(countries)
    if format:
        where += " AND format = ?"
        params.append(format)
    if q.strip():
        where += " AND search LIKE ? ESCAPE '\\'"
        params.append(_like(q.strip()))
    if days != "all":
        where += " AND (start_at IS NULL OR start_at <= ?)"
        params.append(_iso(now + timedelta(days=int(days))))
    if min_score is not None:
        where += " AND score >= ?"
        params.append(min_score)
    if lat is not None:
        delta = math.degrees(radius_km / 6371.0088)
        where += " AND lat BETWEEN ? AND ? AND lon IS NOT NULL AND format <> 'online'"
        params.extend([max(-90, lat - delta), min(90, lat + delta)])
        if abs(lat) + delta < 90:
            width = math.degrees(math.asin(min(1, math.sin(math.radians(delta)) / math.cos(math.radians(lat)))))
            low, high = lon - width, lon + width
            if low < -180:
                where += " AND (lon >= ? OR lon <= ?)"
                params.extend([low + 360, high])
            elif high > 180:
                where += " AND (lon >= ? OR lon <= ?)"
                params.extend([low, high - 360])
            else:
                where += " AND lon BETWEEN ? AND ?"
                params.extend([low, high])
    direction = "DESC" if order == "desc" else "ASC"
    if sort == "start":
        # "Starting soonest": not-yet-started by start, then running ones by end, unknown start last.
        stamp = _iso(now)
        order_by = (f"CASE WHEN start_at IS NULL THEN 2 WHEN start_at >= ? THEN 0 ELSE 1 END, "
                    f"CASE WHEN start_at >= ? THEN start_at END {direction}, "
                    f"COALESCE(end_at, start_at) ASC, key")
        order_params = [stamp, stamp]
    elif sort in {"distance", "foryou"}:
        order_by, order_params = "key", []
    else:
        column = {"prize": "prize_usd", "participants": "participants", "score": "score", "new": "first_seen"}[sort]
        order_by = f"({column} IS NULL), {column} {direction}, start_at ASC, key"
        order_params = []
    with db.connect() as conn:
        total = int(conn.fetchone(f"SELECT COUNT(*) AS n FROM events WHERE {where}", params)["n"])
        select = "data, first_seen, last_seen, score, score_conf, score_detail, lat, lon, cats, flags, start_at, country_code, region, sponsors"
        if sort == "foryou" and lat is None:
            rows = conn.fetchall(f"SELECT {select} FROM events WHERE {where}", params)
            rows.sort(key=lambda r: (-_foryou(r, interests), r["start_at"] or "9", r["first_seen"]))
            rows = rows[(page - 1) * per_page:page * per_page]
        elif lat is None:
            rows = conn.fetchall(f"SELECT {select} FROM events WHERE {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
                                 [*params, *order_params, per_page, (page - 1) * per_page])
        else:
            rows = conn.fetchall(f"SELECT {select} FROM events WHERE {where} ORDER BY {order_by}",
                                 [*params, *order_params])
            for row in rows:
                row["distance_km"] = _distance(lat, lon, row["lat"], row["lon"])
            rows = [row for row in rows if row["distance_km"] <= radius_km]
            if sort == "foryou":
                rows.sort(key=lambda r: (-_foryou(r, interests), r["distance_km"]))
            elif sort == "distance":
                rows.sort(key=lambda row: row["distance_km"], reverse=order == "desc")
            total = len(rows)
            rows = rows[(page - 1) * per_page:page * per_page]
    sources = _source_rows()
    from .score import tier
    events = []
    for row in rows:
        event = {**db.loads(row["data"]), "first_seen": row["first_seen"], "last_seen": row["last_seen"],
                 "score": row["score"], "score_tier": tier(row["score"]),
                 "score_confidence": row["score_conf"] or "low", "score_detail": db.loads(row["score_detail"]),
                 "lat": row["lat"], "lon": row["lon"]}
        event["categories"], event["flags"] = _taxonomy(row, now)
        event["country_code"], event["region"] = _place(row)
        event["country_name"] = country_name(event["country_code"])
        event["sponsors"] = _sponsors(row)
        # Keep scraped source text and the organizer's name on the server: the public listing never shows them,
        # so the API must not hand out organizers' copyrighted descriptions or personal data to every caller.
        for field in _PRIVATE_FIELDS:
            event.pop(field, None)
        if lat is not None:
            event["distance_km"] = round(row["distance_km"], 3)
        events.append(event)
    return {"events": events, "total": total, "page": page, "per_page": per_page,
            "updated_at": _updated_at(sources), "sources": sources}


@app.get("/api/hackathons")
def hackathons(response: Response, kinds: str = "hackathon",
               format: str | None = Query(None, pattern="^(online|in-person|hybrid)$"),
               q: str = "", days: str = Query("all", pattern="^(7|30|all)$"),
               sort: str | None = Query(None, pattern="^(start|prize|participants|score|new|distance|foryou)$"),
               order: str | None = Query(None, pattern="^(asc|desc)$"),
               page: int = Query(1, ge=1), per_page: int = Query(100, ge=1, le=500),
               min_score: int | None = Query(None, ge=0, le=100),
               lat: float | None = Query(None, ge=-90, le=90),
               lon: float | None = Query(None, ge=-180, le=180),
               radius_km: float = Query(100, gt=0, le=2000),
               categories: str = "", types: str = "", interests: str = "",
               region: str = "", country: str = "", sponsors: str = ""):
    response.headers["Cache-Control"] = CDN_CACHE
    if (lat is None) != (lon is None) or (sort == "distance" and lat is None):
        raise HTTPException(422, "Distance search requires both lat and lon")
    sort = sort or ("distance" if lat is not None else "start")
    order = order or ("desc" if sort in {"score", "new", "foryou"} else "asc")
    selected = tuple(sorted({kind.strip() for kind in kinds.split(",") if kind.strip()} - HIDDEN_KINDS))
    cats, kinds_on, likes = _ids(categories, CATEGORIES), _ids(types, TYPES), _ids(interests, CATEGORIES)
    regs, brands = _ids(region, REGIONS), _ids(sponsors, SPONSORS)
    codes = tuple(sorted({c.strip().upper() for c in country.split(",") if c.strip().upper() in COUNTRIES}))
    key = ("hackathons", selected, format, q, days, sort, order, page, per_page, min_score, lat, lon, radius_km,
           cats, kinds_on, likes if sort == "foryou" else (), regs, codes, brands)
    return _cached(key, lambda: _listing(selected, format, q, days, sort, order, page, per_page, min_score, lat, lon,
                                         radius_km, cats, kinds_on, likes, regs, codes, brands))


def _category_counts(kinds: tuple, days: str) -> dict:
    now = utcnow()
    where, params = _upcoming_where(now, list(kinds))
    if days != "all":
        where += " AND (start_at IS NULL OR start_at <= ?)"
        params.append(_iso(now + timedelta(days=int(days))))
    with db.connect() as conn:
        rows = conn.fetchall(f"SELECT data, cats, flags, first_seen, sponsors FROM events WHERE {where}", params)
    counts, flag_counts, brand_counts = dict.fromkeys(CATEGORIES, 0), dict.fromkeys(TYPES, 0), dict.fromkeys(SPONSORS, 0)
    for row in rows:
        for brand in _sponsors(row):
            brand_counts[brand] += 1
        cats, found = _taxonomy(row, now)
        for name in cats:
            counts[name] += 1
        for name in found:
            flag_counts[name] += 1
    order = list(CATEGORIES)
    ranked = sorted(CATEGORIES, key=lambda c: (-counts[c], order.index(c)))
    return {"categories": [{"id": c, "name": CATEGORIES[c], "count": counts[c]} for c in ranked],
            "types": [{"id": t, "name": name, "count": flag_counts[t]} for t, name in TYPES.items()],
            "sponsors": [{"id": b, "name": SPONSORS[b][0], "count": brand_counts[b]}
                         for b in sorted(SPONSORS, key=lambda b: (-brand_counts[b], SPONSORS[b][0].casefold()))]}


@app.get("/api/categories")
def category_list(response: Response, kinds: str = "hackathon", days: str = Query("all", pattern="^(7|30|all)$")):
    response.headers["Cache-Control"] = CDN_CACHE
    selected = tuple(sorted({kind.strip() for kind in kinds.split(",") if kind.strip()} - HIDDEN_KINDS))
    return _cached(("categories", selected, days), lambda: _category_counts(selected, days))


def _region_counts(kinds: tuple, days: str, format: str | None = None) -> dict:
    now = utcnow()
    where, params = _upcoming_where(now, list(kinds))
    if days != "all":
        where += " AND (start_at IS NULL OR start_at <= ?)"
        params.append(_iso(now + timedelta(days=int(days))))
    if format:
        where += " AND format = ?"
        params.append(format)
    with db.connect() as conn:
        rows = conn.fetchall(f"SELECT data, country_code, region FROM events WHERE {where}", params)
    regions, countries = dict.fromkeys(REGIONS, 0), {}
    for row in rows:
        code, region = _place(row)
        if region in regions:
            regions[region] += 1
        if code in COUNTRIES:
            countries[code] = countries.get(code, 0) + 1
    ranked = sorted(countries, key=lambda c: (-countries[c], COUNTRIES[c][0]))
    return {"regions": [{"id": r, "name": name, "count": regions[r]} for r, name in REGIONS.items()],
            "countries": [{"code": c, "name": COUNTRIES[c][0], "region": COUNTRIES[c][1], "count": countries[c]}
                          for c in ranked]}


@app.get("/api/regions")
def region_list(response: Response, kinds: str = "hackathon", days: str = Query("all", pattern="^(7|30|all)$"),
                format: str | None = Query(None, pattern="^(online|in-person|hybrid)$")):
    response.headers["Cache-Control"] = CDN_CACHE
    selected = tuple(sorted({kind.strip() for kind in kinds.split(",") if kind.strip()} - HIDDEN_KINDS))
    return _cached(("regions", selected, days, format), lambda: _region_counts(selected, days, format))


def _stats() -> dict:
    now = utcnow()
    where, params = _upcoming_where(now, ["hackathon"])
    with db.connect() as conn:
        rows = conn.fetchall(f"SELECT start_at, end_at, deadline_at, first_seen FROM events WHERE {where}", params)
    sources = _source_rows()
    open_now = start_48h = new = 0
    for row in rows:
        start, end, deadline, first = (_parse(row[k]) for k in ("start_at", "end_at", "deadline_at", "first_seen"))
        if (deadline is not None and deadline >= now) or (start is not None and start <= now and (end or start) >= now):
            open_now += 1
        if start is not None and now <= start <= now + timedelta(hours=48):
            start_48h += 1
        if first is not None and now - timedelta(days=7) <= first <= now:
            new += 1
    return {"open_now": open_now, "start_48h": start_48h, "new_this_week": new, "total": len(rows),
            "sources": len(sources), "updated_at": _updated_at(sources)}


@app.get("/api/stats")
def stats(response: Response):
    response.headers["Cache-Control"] = CDN_CACHE
    return _cached(("stats",), _stats)


@app.get("/api/sources")
def sources(response: Response):
    response.headers["Cache-Control"] = CDN_CACHE
    return _cached(("sources",), _source_rows)


def _page(name: str) -> str:
    return (STATIC / f"{name}.html").read_text(encoding="utf-8")


def _html(content: str) -> HTMLResponse:
    return HTMLResponse(content, headers={"Cache-Control": CDN_CACHE})


def _landing_counts() -> dict[str, int]:
    def compute():
        counts = {}
        for slug, (_, _, f) in seo.LANDINGS.items():
            counts[slug] = _listing(tuple(f.get("kinds", ("hackathon",))), f.get("format"), "", "all", "start", "asc",
                                    1, 1, categories=f.get("categories", ()), regions=f.get("regions", ()),
                                    countries=f.get("countries", ()))["total"]
        return counts
    return _cached(("landing_counts",), compute)


def _directory(request: Request, slug: str | None, page: int) -> HTMLResponse:
    """The directory page with its first rows, pagination links and metadata already in the HTML."""
    if slug is not None and slug not in seo.LANDINGS:
        raise HTTPException(404, "No such page")
    heading, phrase, f = seo.LANDINGS[slug] if slug else ("Upcoming hackathons", "upcoming hackathons worldwide", {})
    kinds = tuple(f.get("kinds", ("hackathon",)))
    args = (kinds, f.get("format"), "", "all", "start", "asc", page, seo.PER_PAGE)
    extra = dict(categories=f.get("categories", ()), regions=f.get("regions", ()), countries=f.get("countries", ()))
    data = _cached(("ssr", slug, page), lambda: _listing(*args, **extra))
    total, events = data["total"], data["events"]
    pages = max(1, -(-total // seo.PER_PAGE))
    if page > pages:
        raise HTTPException(404, "No such page")
    base = seo.site_url(str(request.base_url))
    path = f"/hackathons/{slug}" if slug else "/hackathons"
    text = seo.intro(phrase, total, events)
    title = f"{heading} | {seo.SITE_NAME}" if slug else f"Upcoming hackathons worldwide | {seo.SITE_NAME}"
    if page > 1:
        title = f"{heading}, page {page} | {seo.SITE_NAME}"
    crumbs = [{"@type": "ListItem", "position": 1, "name": "Hackathons", "item": f"{base}/hackathons"}]
    if slug:
        crumbs.append({"@type": "ListItem", "position": 2, "name": heading, "item": base + path})
    ld = seo.json_ld({"@context": "https://schema.org", "@type": "CollectionPage", "name": heading, "description": text,
                      "url": base + path, "breadcrumb": {"@type": "BreadcrumbList", "itemListElement": crumbs}})
    preset = f"<script>window.HF_PRESET={json.dumps(seo.preset(f))};window.HF_PAGE={page};</script>"
    canonical = base + path + (f"?page={page}" if page > 1 else "")
    html = seo.with_head(_page("hackathons"), seo.head(title, text, canonical, ld + preset,
                                                       noindex=bool(slug) and total < seo.MIN_EVENTS))
    h1 = escape(heading) if slug else "Ready, set, build"
    html = html.replace('<h1>Ready, set, build<span class="brand-dot">.</span></h1><p class="muted">Good opportunities. Zero noise. Your next project starts here.</p>',
                        f'<h1>{h1}<span class="brand-dot">.</span></h1><p class="muted">{escape(text)}</p>')
    html = html.replace('<tbody id="events-body"></tbody>', f'<tbody id="events-body">{seo.rows(events)}</tbody>')
    html = html.replace('<strong id="result-count">—</strong>', f'<strong id="result-count">{total:,}</strong>')
    html = html.replace('<footer class="pagination">', seo.pages_nav(path, page, total) + '<footer class="pagination">', 1)
    html = html.replace('</p></section></main>', '</p>' + seo.browse_links(_landing_counts(), slug) + '</section></main>', 1)
    return _html(html)


@app.get("/")
def landing(request: Request):
    base = seo.site_url(str(request.base_url))
    ld = seo.json_ld({"@context": "https://schema.org", "@type": "WebSite", "name": seo.SITE_NAME, "url": base + "/",
                      "description": seo.TAGLINE})
    html = seo.with_head(_page("index"), seo.head(
        f"{seo.SITE_NAME}: {seo.TAGLINE}",
        "Hackfinder lists upcoming hackathons, game jams and buildathons worldwide, online and near you, "
        "with filters for country, topic and sponsor and an open score for every event.", base + "/", ld))
    html = html.replace("</main>", seo.browse_links(_landing_counts()) + "</main>", 1)
    return _html(html)


@app.get("/hackathons")
def listing(request: Request, page: int = Query(1, ge=1, le=1000)):
    return _directory(request, None, page)


@app.get("/hackathons/{slug}")
def landing_page(request: Request, slug: str, page: int = Query(1, ge=1, le=1000)):
    return _directory(request, slug, page)


@app.get("/robots.txt")
def robots(request: Request):
    return PlainTextResponse(seo.robots(seo.site_url(str(request.base_url))), headers={"Cache-Control": CDN_CACHE})


@app.get("/sitemap.xml")
def sitemap(request: Request):
    base = seo.site_url(str(request.base_url))
    updated = _updated_at(_cached(("sources",), _source_rows))
    counts = _landing_counts()
    paths = [("/", updated), ("/hackathons", updated), ("/near", None), ("/methodology", None)]
    paths += [(f"/hackathons/{slug}", updated) for slug in seo.LANDINGS if counts.get(slug, 0) >= seo.MIN_EVENTS]
    return Response(seo.sitemap(base, paths), media_type="application/xml", headers={"Cache-Control": CDN_CACHE})


_STATIC_PAGES = {"index.html": "/", "hackathons.html": "/hackathons", "near.html": "/near", "methodology.html": "/methodology"}

# 'unsafe-inline' is kept because the pages carry small inline scripts (filter preset, analytics init) and inline
# styles; the rest of the policy still blocks framing, external scripts, plugins and off-site form posts and beacons.
# img allows Google's favicon service; connect/script allow Vercel's analytics; geolocation stays on for "Near me".
_CSP = ("default-src 'self'; img-src 'self' https://www.google.com https://*.gstatic.com data:; "
        "script-src 'self' 'unsafe-inline' https://va.vercel-scripts.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://*.gstatic.com; "
        "connect-src 'self' https://vitals.vercel-insights.com; object-src 'none'; "
        "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=(), payment=(), usb=()",
}


@app.middleware("http")
async def security_and_canonical(request: Request, call_next):
    """Set security headers on every response, and send /static/<page>.html to its real route."""
    name = request.url.path.removeprefix("/static/")
    if request.url.path.startswith("/static/") and name in _STATIC_PAGES:
        response = RedirectResponse(_STATIC_PAGES[name], status_code=301)
    else:
        response = await call_next(request)
    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


app.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")


def _distance(lat, lon, other_lat, other_lon):
    a, b = math.radians(lat), math.radians(other_lat)
    h = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(math.radians(other_lon - lon) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


@app.get("/api/places")
def places(response: Response, q: str = "", limit: int = Query(8, ge=1, le=50)):
    response.headers["Cache-Control"] = CDN_CACHE
    prefix = " ".join("".join(c for c in unicodedata.normalize("NFKD", q.casefold())
                              if not unicodedata.combining(c)).split())

    def query():
        with db.connect() as conn:
            escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            return conn.fetchall("""SELECT name, country, country_code, lat, lon, population FROM places
                                     WHERE ascii_name LIKE ? ESCAPE '\\' ORDER BY population DESC, name LIMIT ?""",
                                  (escaped + "%", limit))
    return _cached(("places", prefix, limit), query)


@app.get("/api/methodology")
def methodology(response: Response):
    from .score import methodology as describe
    response.headers["Cache-Control"] = CDN_CACHE
    return _cached(("methodology",), describe)


@app.get("/near")
def near(request: Request):
    base = seo.site_url(str(request.base_url))
    return _html(seo.with_head(_page("near"), seo.head(
        f"Hackathons near me | {seo.SITE_NAME}",
        "Find in-person and hybrid hackathons near you. Pick a city or share your location and see events within 25 to 500 km.",
        base + "/near")))


@app.get("/methodology")
def methodology_page(request: Request):
    base = seo.site_url(str(request.base_url))
    return _html(seo.with_head(_page("methodology"), seo.head(
        f"How the Hackfinder Score works | {seo.SITE_NAME}",
        "The open formula behind the Hackfinder Score: how prizes, community size, support and evidence combine into a 0 to 100 rating.",
        base + "/methodology")))
