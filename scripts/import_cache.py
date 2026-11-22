"""One-off import of data/cache.json (the old live cache) into the database.

    .venv\\Scripts\\python scripts\\import_cache.py [path/to/cache.json]

Uses DATABASE_URL when set, otherwise the local SQLite file. Meant for a fresh
database: rows are upserted (re-running is harmless, but it replaces newer crawled
copies of the same listings), and first-seen times come from data/seen.json.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hackfinder import db, store  # noqa: E402
from hackfinder.dedupe import event_key  # noqa: E402
from hackfinder.models import Event  # noqa: E402


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    result = datetime.fromisoformat(value)
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else ROOT / "data" / "cache.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        seen = json.loads((path.parent / "seen.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = {}
    updated = _date(data.get("updated_at")) or store.utcnow()
    by_source = data.get("by_source")
    if by_source is None:
        by_source = {}
        for row in data.get("events", []):
            by_source.setdefault(row["source"], []).append(row)
    db.init()
    imported = 0
    with db.connect() as conn:
        for meta in data.get("sources", []):
            store.register_source(conn, meta)
            ok = meta.get("status") == "ok"
            conn.execute("""UPDATE sources SET last_run_at = ?, last_success_at = COALESCE(last_success_at, ?),
                                last_error = ?, last_count = ?, last_duration_ms = ? WHERE id = ?""",
                         (store.iso(updated), store.iso(updated) if ok else None, meta.get("error"),
                          meta.get("count"), meta.get("duration_ms"), meta["id"]))
        for cid, rows in by_source.items():
            pairs = []
            for row in rows:
                event = Event.model_validate(row).model_copy(update={"source": cid})
                if not store.is_junk(event):
                    pairs.append((event, store.clean(event)))
            imported += store.upsert_sources(conn, cid, "*", pairs, updated)
            # Keep the original first-seen times so "new this week" stays meaningful.
            conn.executemany("UPDATE event_sources SET first_seen = ? WHERE source = ? AND event_key = ? AND first_seen > ?",
                             [(store.iso(_date(seen[event_key(e)])), cid, event_key(e), store.iso(_date(seen[event_key(e)])))
                              for _, e in pairs if seen.get(event_key(e))])
        active = store.remerge(conn)
    print(f"Imported {imported} source rows from {path.name}; {active} active merged events ({db.backend()}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
