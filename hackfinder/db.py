"""Database access: Postgres (psycopg) when DATABASE_URL is set, otherwise local SQLite.

SQL is written once in the portable subset both engines accept: `?` placeholders,
ON CONFLICT upserts, TRUE/FALSE literals, ISO-8601 UTC timestamps stored as TEXT.
JSON columns are JSONB on Postgres and TEXT on SQLite; write them with
`CAST(? AS JSONTYPE)` and read them back with `loads()`.

    from hackfinder import db
    db.init()
    with db.connect() as conn:            # one transaction; commits on success
        rows = conn.fetchall("SELECT key FROM events WHERE status = ?", ("active",))
"""
from __future__ import annotations

import atexit
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterable, Iterator

ROOT = Path(__file__).resolve().parent.parent

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS events (
        key TEXT PRIMARY KEY,
        data JSONTYPE NOT NULL,
        source TEXT NOT NULL,
        kind TEXT NOT NULL,
        format TEXT NOT NULL,
        title TEXT NOT NULL,
        search TEXT NOT NULL,
        start_at TEXT,
        end_at TEXT,
        deadline_at TEXT,
        prize_usd REALTYPE,
        participants INTEGER,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS events_listing ON events (status, kind, start_at)",
    """CREATE TABLE IF NOT EXISTS event_sources (
        source TEXT NOT NULL,
        ident TEXT NOT NULL,
        scope_key TEXT NOT NULL,
        event_key TEXT NOT NULL,
        raw JSONTYPE NOT NULL,
        data JSONTYPE NOT NULL,
        content_hash TEXT NOT NULL,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        miss_count INTEGER NOT NULL DEFAULT 0,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        PRIMARY KEY (source, ident)
    )""",
    "CREATE INDEX IF NOT EXISTS event_sources_scope ON event_sources (source, scope_key, active)",
    """CREATE TABLE IF NOT EXISTS sources (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        method TEXT NOT NULL,
        last_run_at TEXT,
        last_success_at TEXT,
        last_error TEXT,
        last_count INTEGER,
        last_duration_ms INTEGER,
        backoff_until TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS scopes (
        source TEXT NOT NULL,
        scope_key TEXT NOT NULL,
        last_crawled_at TEXT,
        last_count INTEGER,
        saturated BOOLEAN NOT NULL DEFAULT FALSE,
        last_error TEXT,
        PRIMARY KEY (source, scope_key)
    )""",
    """CREATE TABLE IF NOT EXISTS crawl_runs (
        id SERIALTYPE,
        pass_name TEXT NOT NULL,
        source TEXT NOT NULL,
        scope_key TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL,
        status TEXT NOT NULL,
        rows INTEGER NOT NULL DEFAULT 0,
        exhaustive BOOLEAN NOT NULL DEFAULT FALSE,
        error TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS crawl_runs_source ON crawl_runs (source, scope_key, started_at)",
]

_TYPES = {
    "postgres": {"JSONTYPE": "JSONB", "REALTYPE": "DOUBLE PRECISION",
                 "SERIALTYPE": "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"},
    "sqlite": {"JSONTYPE": "TEXT", "REALTYPE": "REAL", "SERIALTYPE": "INTEGER PRIMARY KEY AUTOINCREMENT"},
}

_lock = threading.Lock()
_pool = None
_max_connections = int(os.getenv("HF_DB_POOL_MAX", "2"))


def url() -> str | None:
    return os.getenv("DATABASE_URL") or None


def backend() -> str:
    return "postgres" if url() else "sqlite"


def sqlite_path() -> Path:
    return Path(os.getenv("HF_DB_PATH") or ROOT / "data" / "hackfinder.db")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value: Any) -> Any:
    """JSONB arrives decoded from psycopg; TEXT from SQLite still needs parsing."""
    return json.loads(value) if isinstance(value, (str, bytes)) else value


class Connection:
    """Thin adapter so callers write one dialect and always get dict rows."""

    def __init__(self, raw, kind: str):
        self.raw = raw
        self.kind = kind

    def _sql(self, sql: str) -> str:
        for token, name in _TYPES[self.kind].items():
            sql = sql.replace(token, name)
        # psycopg treats every "%" as a placeholder marker, so literal ones (LIKE '%,ai,%') become "%%".
        return sql.replace("%", "%%").replace("?", "%s") if self.kind == "postgres" else sql

    def execute(self, sql: str, params: Iterable[Any] = ()):
        return self.raw.execute(self._sql(sql), tuple(params))

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]):
        rows = [tuple(row) for row in rows]
        if not rows:
            return
        if self.kind == "postgres":
            with self.raw.cursor() as cursor:
                cursor.executemany(self._sql(sql), rows)
        else:
            self.raw.executemany(self._sql(sql), rows)

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        return [dict(row) for row in self.execute(sql, params).fetchall()]

    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        row = self.execute(sql, params).fetchone()
        return dict(row) if row is not None else None


def configure(max_connections: int) -> None:
    """Set the Postgres pool size before first use (the worker uses 1)."""
    global _max_connections
    with _lock:
        _max_connections = max(1, max_connections)


def _get_pool():
    global _pool
    with _lock:
        if _pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            # prepare_threshold=None keeps PgBouncer/Neon pooled URLs safe.
            _pool = ConnectionPool(url(), min_size=1, max_size=_max_connections, open=True,
                                   check=ConnectionPool.check_connection, name="hackfinder",
                                   kwargs={"row_factory": dict_row, "prepare_threshold": None})
            atexit.register(close)  # stop pool threads cleanly when a script or worker exits
        return _pool


def close() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def connect() -> Iterator[Connection]:
    if backend() == "postgres":
        with _get_pool().connection() as raw:  # commits on success, rolls back on error
            yield Connection(raw, "postgres")
        return
    path = sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path, timeout=30)
    raw.row_factory = sqlite3.Row
    try:
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute("PRAGMA busy_timeout=30000")
        yield Connection(raw, "sqlite")
        raw.commit()
    except BaseException:
        raw.rollback()
        raise
    finally:
        raw.close()


def init(*, places: bool = False) -> None:
    """Create the tables if they are missing. Safe to call on every start."""
    with connect() as conn:
        for statement in _SCHEMA:
            conn.execute(statement)

        columns = {"score": "SMALLINT", "score_conf": "TEXT", "score_detail": "JSONTYPE",
                   "score_version": "TEXT", "lat": "REALTYPE", "lon": "REALTYPE",
                   "cats": "TEXT", "flags": "TEXT"}
        present = {r["name"] for r in conn.fetchall("PRAGMA table_info(events)")} if conn.kind == "sqlite" else set()
        for name, type_name in columns.items():
            if conn.kind == "postgres":
                conn.execute(f"ALTER TABLE events ADD COLUMN IF NOT EXISTS {name} {type_name}")
            elif name not in present:
                conn.execute(f"ALTER TABLE events ADD COLUMN {name} {type_name}")
        conn.execute("CREATE INDEX IF NOT EXISTS events_score ON events (status, kind, score)")
        conn.execute("""CREATE TABLE IF NOT EXISTS places (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, ascii_name TEXT NOT NULL, country TEXT NOT NULL,
            country_code TEXT NOT NULL, lat REALTYPE NOT NULL, lon REALTYPE NOT NULL, population INTEGER NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS places_name ON places (ascii_name)")
        conn.execute("CREATE TABLE IF NOT EXISTS score_cache (key TEXT PRIMARY KEY, data JSONTYPE NOT NULL)")
        if places:
            from .geo import populate
            populate(conn)
