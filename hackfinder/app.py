"""Read-only FastAPI app: JSON endpoints over the database, and the static frontend.

Nothing here crawls. The worker (hackfinder/worker.py) fills the database; this module
must not import collectors or any scraping library, so the Vercel bundle stays small.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import math
import unicodedata
from pathlib import Path
import threading
import time

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .categories import CATEGORIES, NEW_DAYS, TYPES, categorize, flags, unpack

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
CACHE_SECONDS = float(os.getenv("HF_API_CACHE_SECONDS", "30"))
CDN_CACHE = "public, s-maxage=60, stale-while-revalidate=300"
HIDDEN_KINDS = {"other", "unknown"}

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


def _foryou(row: dict, interests: tuple) -> float:
    hits = sum(1 for i in interests if f",{i}," in (row["cats"] or ","))
    return (45 if row["score"] is None else row["score"]) + 12 * min(hits, 2)


def _listing(kinds: tuple, format: str | None, q: str, days: str, sort: str, order: str,
             page: int, per_page: int, min_score=None, lat=None, lon=None, radius_km=100,
             categories: tuple = (), types: tuple = (), interests: tuple = ()) -> dict:
    now = utcnow()
    where, params = _upcoming_where(now, list(kinds))
    if categories:
        where += " AND (" + " OR ".join(_has("cats", c) for c in categories) + ")"
    for kind_flag in types:
        if kind_flag == "new":
            where += " AND first_seen >= ?"
            params.append(_new_cutoff(now))
        else:
            where += " AND " + _has("flags", kind_flag)
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
        select = "data, first_seen, last_seen, score, score_conf, score_detail, lat, lon, cats, flags, start_at"
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
        # Extraction-only source text is never part of the public listing.
        event["signals"] = {k: v for k, v in event.get("signals", {}).items() if k != "text"}
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
               categories: str = "", types: str = "", interests: str = ""):
    response.headers["Cache-Control"] = CDN_CACHE
    if (lat is None) != (lon is None) or (sort == "distance" and lat is None):
        raise HTTPException(422, "Distance search requires both lat and lon")
    sort = sort or ("distance" if lat is not None else "start")
    order = order or ("desc" if sort in {"score", "new", "foryou"} else "asc")
    selected = tuple(sorted({kind.strip() for kind in kinds.split(",") if kind.strip()} - HIDDEN_KINDS))
    cats, kinds_on, likes = _ids(categories, CATEGORIES), _ids(types, TYPES), _ids(interests, CATEGORIES)
    key = ("hackathons", selected, format, q, days, sort, order, page, per_page, min_score, lat, lon, radius_km,
           cats, kinds_on, likes if sort == "foryou" else ())
    return _cached(key, lambda: _listing(selected, format, q, days, sort, order, page, per_page, min_score, lat, lon,
                                         radius_km, cats, kinds_on, likes))


def _category_counts(kinds: tuple, days: str) -> dict:
    now = utcnow()
    where, params = _upcoming_where(now, list(kinds))
    if days != "all":
        where += " AND (start_at IS NULL OR start_at <= ?)"
        params.append(_iso(now + timedelta(days=int(days))))
    with db.connect() as conn:
        rows = conn.fetchall(f"SELECT data, cats, flags, first_seen FROM events WHERE {where}", params)
    counts, flag_counts = dict.fromkeys(CATEGORIES, 0), dict.fromkeys(TYPES, 0)
    for row in rows:
        cats, found = _taxonomy(row, now)
        for name in cats:
            counts[name] += 1
        for name in found:
            flag_counts[name] += 1
    order = list(CATEGORIES)
    ranked = sorted(CATEGORIES, key=lambda c: (-counts[c], order.index(c)))
    return {"categories": [{"id": c, "name": CATEGORIES[c], "count": counts[c]} for c in ranked],
            "types": [{"id": t, "name": name, "count": flag_counts[t]} for t, name in TYPES.items()]}


@app.get("/api/categories")
def category_list(response: Response, kinds: str = "hackathon", days: str = Query("all", pattern="^(7|30|all)$")):
    response.headers["Cache-Control"] = CDN_CACHE
    selected = tuple(sorted({kind.strip() for kind in kinds.split(",") if kind.strip()} - HIDDEN_KINDS))
    return _cached(("categories", selected, days), lambda: _category_counts(selected, days))


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


@app.get("/")
def landing():
    return FileResponse(STATIC / "index.html")


@app.get("/hackathons")
def listing():
    return FileResponse(STATIC / "hackathons.html")


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
def near():
    return FileResponse(STATIC / "near.html")


@app.get("/methodology")
def methodology_page():
    return FileResponse(STATIC / "methodology.html")
