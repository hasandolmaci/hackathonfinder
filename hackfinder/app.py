"""Read-only FastAPI app: JSON endpoints over the database, and the static frontend.

Nothing here crawls. The worker (hackfinder/worker.py) fills the database; this module
must not import collectors or any scraping library, so the Vercel bundle stays small.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import threading
import time

from fastapi import FastAPI, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db

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


def _listing(kinds: tuple, format: str | None, q: str, days: str, sort: str, order: str,
             page: int, per_page: int) -> dict:
    now = utcnow()
    where, params = _upcoming_where(now, list(kinds))
    if format:
        where += " AND format = ?"
        params.append(format)
    if q.strip():
        where += " AND search LIKE ? ESCAPE '\\'"
        params.append(_like(q.strip()))
    if days != "all":
        where += " AND (start_at IS NULL OR start_at <= ?)"
        params.append(_iso(now + timedelta(days=int(days))))
    direction = "DESC" if order == "desc" else "ASC"
    if sort == "start":
        # "Starting soonest": not-yet-started by start, then running ones by end, unknown start last.
        stamp = _iso(now)
        order_by = (f"CASE WHEN start_at IS NULL THEN 2 WHEN start_at >= ? THEN 0 ELSE 1 END, "
                    f"CASE WHEN start_at >= ? THEN start_at END {direction}, "
                    f"COALESCE(end_at, start_at) ASC, key")
        order_params = [stamp, stamp]
    else:
        column = {"prize": "prize_usd", "participants": "participants"}[sort]
        order_by = f"({column} IS NULL), {column} {direction}, start_at ASC, key"
        order_params = []
    with db.connect() as conn:
        total = int(conn.fetchone(f"SELECT COUNT(*) AS n FROM events WHERE {where}", params)["n"])
        rows = conn.fetchall(f"SELECT data, first_seen, last_seen FROM events WHERE {where} "
                             f"ORDER BY {order_by} LIMIT ? OFFSET ?",
                             [*params, *order_params, per_page, (page - 1) * per_page])
    sources = _source_rows()
    events = [{**db.loads(r["data"]), "first_seen": r["first_seen"], "last_seen": r["last_seen"]} for r in rows]
    return {"events": events, "total": total, "page": page, "per_page": per_page,
            "updated_at": _updated_at(sources), "sources": sources}


@app.get("/api/hackathons")
def hackathons(response: Response, kinds: str = "hackathon",
               format: str | None = Query(None, pattern="^(online|in-person|hybrid)$"),
               q: str = "", days: str = Query("all", pattern="^(7|30|all)$"),
               sort: str = Query("start", pattern="^(start|prize|participants)$"),
               order: str = Query("asc", pattern="^(asc|desc)$"),
               page: int = Query(1, ge=1), per_page: int = Query(100, ge=1, le=500)):
    response.headers["Cache-Control"] = CDN_CACHE
    selected = tuple(sorted({kind.strip() for kind in kinds.split(",") if kind.strip()} - HIDDEN_KINDS))
    key = ("hackathons", selected, format, q, days, sort, order, page, per_page)
    return _cached(key, lambda: _listing(selected, format, q, days, sort, order, page, per_page))


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
