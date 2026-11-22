"""Event storage rules: display hygiene, per-source upserts, lifecycle, and the merged view.

event_sources holds what each source said; events is rebuilt from the active,
not-yet-past source rows with dedupe(). Failed or partial crawls never call
mark_misses(), so they cannot hide anything.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re

from . import db
from .dedupe import dedupe, event_key, normalize_url
from .models import Event

MISSES_BEFORE_INACTIVE = 2


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    """One sortable text form for every stored timestamp."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def day_start(now: datetime) -> str:
    """Events whose end (or start) is before this are past."""
    return iso(now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0))


_ZERO_PRIZE = re.compile(r"^\D{0,6}0+(?:[.,]0+)?\D{0,6}$")


_JUNK_TITLE = re.compile(r"^\s*(test|testing|demo|sample|untitled|asdf+|qwerty)\s*\d*\s*$", re.I)


def is_junk(event: Event) -> bool:
    return len(event.title.strip()) < 3 or bool(_JUNK_TITLE.match(event.title))


def clean(event: Event) -> Event:
    """Display hygiene shared by all sources."""
    prize = (event.prize or "").strip()
    if not prize or _ZERO_PRIZE.match(prize) or event.prize_usd == 0:
        prize = None
    elif len(prize) > 60:
        prize = prize[:57].rsplit(" ", 1)[0].rstrip(";,") + "…"
    updates = {"prize": prize}
    if event.prize_usd == 0:
        updates["prize_usd"] = None
    return event.model_copy(update=updates)


def ident(event: Event) -> str:
    return f"id:{event.source_id}" if event.source_id else f"url:{normalize_url(event.url)}"


def _hash(event: Event) -> str:
    payload = event.model_dump(mode="json", exclude={"fetched_at", "also_on"})
    return hashlib.sha256(db.dumps(payload).encode("utf-8")).hexdigest()


def _past(event: Event, cutoff: str) -> bool:
    when = event.end or event.start
    return when is not None and iso(when) < cutoff


def upsert_sources(conn: db.Connection, source: str, scope_key: str,
                   pairs: list[tuple[Event, Event]], seen_at: datetime) -> int:
    """Store (raw, processed) pairs for one source/scope. Seen rows become active again."""
    now = iso(seen_at)
    rows = {}
    for raw, event in pairs:
        rows[ident(event)] = (source, ident(event), scope_key, event_key(event),
                              db.dumps(raw.model_dump(mode="json")), db.dumps(event.model_dump(mode="json")),
                              _hash(event), now, now)
    conn.executemany(
        """INSERT INTO event_sources (source, ident, scope_key, event_key, raw, data, content_hash,
                                      first_seen, last_seen, miss_count, active)
           VALUES (?, ?, ?, ?, CAST(? AS JSONTYPE), CAST(? AS JSONTYPE), ?, ?, ?, 0, TRUE)
           ON CONFLICT (source, ident) DO UPDATE SET
               scope_key = excluded.scope_key, event_key = excluded.event_key, raw = excluded.raw,
               data = excluded.data, content_hash = excluded.content_hash,
               last_seen = excluded.last_seen, miss_count = 0, active = TRUE""",
        rows.values())
    return len(rows)


def active_count(conn: db.Connection, source: str, scope_key: str) -> int:
    row = conn.fetchone("SELECT COUNT(*) AS n FROM event_sources WHERE source = ? AND scope_key = ? AND active = TRUE",
                        (source, scope_key))
    return int(row["n"]) if row else 0


def mark_misses(conn: db.Connection, source: str, scope_key: str, run_started: datetime) -> None:
    """Call only after a successful, exhaustive crawl of this source/scope."""
    started = iso(run_started)
    conn.execute("""UPDATE event_sources SET miss_count = miss_count + 1
                    WHERE source = ? AND scope_key = ? AND active = TRUE AND last_seen < ?""",
                 (source, scope_key, started))
    conn.execute("""UPDATE event_sources SET active = FALSE
                    WHERE source = ? AND scope_key = ? AND active = TRUE AND miss_count >= ?""",
                 (source, scope_key, MISSES_BEFORE_INACTIVE))


def _search_text(event: Event) -> str:
    parts = [event.title, event.description, event.location, event.organizer, " ".join(event.tags)]
    return " ".join(p for p in parts if p).casefold()


def remerge(conn: db.Connection, now: datetime | None = None) -> int:
    """Rebuild the merged events table from active source rows. Returns active event count."""
    now = now or utcnow()
    stamp, cutoff = iso(now), day_start(now)
    rows = conn.fetchall("SELECT source, ident, event_key, data, first_seen, last_seen FROM event_sources WHERE active = TRUE")
    seen = {(r["source"], r["ident"]): (r["first_seen"], r["last_seen"]) for r in rows}
    first_by_key: dict[str, str] = {}
    for row in rows:
        first = first_by_key.get(row["event_key"])
        first_by_key[row["event_key"]] = min(first, row["first_seen"]) if first else row["first_seen"]
    current = [e for e in (Event.model_validate(db.loads(r["data"])) for r in rows) if not _past(e, cutoff)]
    existing = {r["key"]: r["first_seen"] for r in conn.fetchall("SELECT key, first_seen FROM events")}
    from .score import Context, prize_usd
    history = [Event.model_validate(db.loads(r["data"])) for r in conn.fetchall("SELECT data FROM events")]
    rate_row = conn.fetchone("SELECT data FROM score_cache WHERE key = 'ecb'")
    rates = db.loads(rate_row["data"])["rates"] if rate_row else None
    recent = iso(now - timedelta(days=180))
    cohort = [Event.model_validate(db.loads(r["data"])) for r in rows if r["last_seen"] >= recent]
    context = Context([e for e in cohort if not _past(e, cutoff)], history, rates)
    merged = {}
    for event in dedupe(current):
        event = event.model_copy(update={"prize_usd": prize_usd(event, rates)})
        key = event_key(event)
        first, last = seen.get((event.source, ident(event)), (stamp, stamp))
        first = min(x for x in (existing.get(key), first_by_key.get(key), first) if x)
        merged[key] = (key, db.dumps(event.model_dump(mode="json")), event.source, event.kind, event.format,
                       event.title, _search_text(event), iso(event.start), iso(event.end),
                       iso(event.registration_deadline), event.prize_usd, event.participants,
                       first, last, stamp)
    conn.executemany(
        """INSERT INTO events (key, data, source, kind, format, title, search, start_at, end_at, deadline_at,
                               prize_usd, participants, first_seen, last_seen, status, updated_at)
           VALUES (?, CAST(? AS JSONTYPE), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
           ON CONFLICT (key) DO UPDATE SET
               data = excluded.data, source = excluded.source, kind = excluded.kind, format = excluded.format,
               title = excluded.title, search = excluded.search, start_at = excluded.start_at,
               end_at = excluded.end_at, deadline_at = excluded.deadline_at, prize_usd = excluded.prize_usd,
               participants = excluded.participants, first_seen = excluded.first_seen,
               last_seen = excluded.last_seen, status = 'active', updated_at = excluded.updated_at""",
        merged.values())
    rescore(conn, context)
    gone = conn.fetchall("SELECT key, start_at, end_at FROM events WHERE status <> ?", ("expired",))
    updates = []
    for row in gone:
        if row["key"] in merged:
            continue
        when = row["end_at"] or row["start_at"]
        updates.append(("expired" if when is not None and when < cutoff else "missing", stamp, row["key"]))
    conn.executemany("UPDATE events SET status = ?, updated_at = ? WHERE key = ?", updates)
    return len(merged)


def register_source(conn: db.Connection, meta: dict) -> None:
    conn.execute("""INSERT INTO sources (id, name, method) VALUES (?, ?, ?)
                    ON CONFLICT (id) DO UPDATE SET name = excluded.name, method = excluded.method""",
                 (meta["id"], meta.get("name", meta["id"]), meta.get("method", "api")))


def record_source(conn: db.Connection, source: str, *, ran_at: datetime, ok: bool, error: str | None,
                  count: int, duration_ms: int, backoff_until: datetime | None = None) -> None:
    conn.execute("""UPDATE sources SET last_run_at = ?, last_success_at = CASE WHEN ? THEN ? ELSE last_success_at END,
                        last_error = ?, last_count = ?, last_duration_ms = ?, backoff_until = ?
                    WHERE id = ?""",
                 (iso(ran_at), ok, iso(ran_at), error, count, duration_ms, iso(backoff_until), source))


def record_scope(conn: db.Connection, source: str, scope_key: str, *, crawled_at: datetime,
                 count: int, saturated: bool, error: str | None) -> None:
    conn.execute("""INSERT INTO scopes (source, scope_key, last_crawled_at, last_count, saturated, last_error)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (source, scope_key) DO UPDATE SET
                        last_crawled_at = excluded.last_crawled_at, last_count = excluded.last_count,
                        saturated = excluded.saturated, last_error = excluded.last_error""",
                 (source, scope_key, iso(crawled_at), count, saturated, error))


def record_run(conn: db.Connection, *, pass_name: str, source: str, scope_key: str, started_at: datetime,
               finished_at: datetime, status: str, rows: int, exhaustive: bool, error: str | None) -> None:
    conn.execute("""INSERT INTO crawl_runs (pass_name, source, scope_key, started_at, finished_at,
                                            status, rows, exhaustive, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (pass_name, source, scope_key, iso(started_at), iso(finished_at), status, rows, exhaustive, error))


def rescore(conn: db.Connection, context=None) -> int:
    """Refresh every stored score and coordinate, including historical editions."""
    from .geo import geocode
    from .score import Context, VERSION, score_event

    rows = conn.fetchall("SELECT key, data FROM events")
    events = [Event.model_validate(db.loads(row["data"])) for row in rows]
    if context is None:
        active = [Event.model_validate(db.loads(row["data"])) for row in
                  conn.fetchall("SELECT data FROM event_sources WHERE active = TRUE AND last_seen >= ?",
                                (iso(utcnow() - timedelta(days=180)),))]
        rate_row = conn.fetchone("SELECT data FROM score_cache WHERE key = 'ecb'")
        context = Context(active, events, db.loads(rate_row["data"])["rates"] if rate_row else None)
    updates = []
    for row, event in zip(rows, events):
        result = score_event(event, context)
        lat, lon = geocode(event.location, event.country, event.format)
        updates.append((result["score"], result["score_confidence"], db.dumps(result["score_detail"]),
                        VERSION, lat, lon, row["key"]))
    conn.executemany("""UPDATE events SET score = ?, score_conf = ?, score_detail = CAST(? AS JSONTYPE),
                        score_version = ?, lat = ?, lon = ? WHERE key = ?""", updates)
    return len(updates)
