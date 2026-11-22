"""Crawler worker: run one pass of collectors and write the results to the database.

    python -m hackfinder.worker --pass quick|browser|full [--only luma,devpost]

Sources run in parallel (at most 6 at a time); scopes of one source run in order.
A collector may define `scopes(pass_name) -> list[str]` and `collect_scope(scope)`;
otherwise `collect()` is one scope named "*". Each scope is upserted as soon as it
finishes. Optional `SCOPE_LIMIT = n` marks a scope that returns >= n rows as
saturated (a ranked search that may hide events), so it never counts as exhaustive.
`RANKED_SEARCH = True` marks every scope of a source as saturated: its results are a
filtered or ranked sample (Luma, Meetup), so its events expire only by date.

Collector errors are recorded per source and never stop the run; the exit code is
non-zero only when the database fails.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import importlib
import logging
import os
import re
import sys
import threading
import time
from types import ModuleType

from . import db, store
from .classify import classify
from .models import Event
from .store import utcnow

log = logging.getLogger(__name__)

PASSES = {
    "quick": ["devpost", "devfolio", "unstop", "hackclub", "ctftime", "mlh", "taikai", "hackerearth", "luma",
              "allhackathons", "zindi", "devnovate", "hack2skill", "hackquest", "commudle", "hackjunction"],
    "browser": ["ethglobal", "kaggle", "itchio", "hackathoncom", "lablab",
                "dorahacks", "encodeclub", "wemakedevs"],
    "full": None,  # every collector (minus LOCAL_ONLY when running in GitHub Actions)
    "local": None,  # LOCAL_ONLY, run from a home computer (scripts/crawl_local.ps1)
}
# Sources that block datacenter IPs (verified from GitHub Actions on 2026-11-22: Eventbrite HTTP 405
# even to real Chrome, Global Game Jam Cloudflare 403). They work from a home connection.
LOCAL_ONLY = ["eventbrite", "globalgamejam"]
PASSES["local"] = LOCAL_ONLY
SOURCE_TIMEOUT = {"quick": 15 * 60, "browser": 15 * 60, "full": 50 * 60, "local": 50 * 60}
MAX_PARALLEL = 6
BLOCK_BACKOFF = timedelta(hours=2)
_BLOCKED = re.compile(r"\b(403|429)\b|forbidden|too many requests", re.I)
_db_lock = threading.Lock()  # one writer at a time: SQLite locking, one Postgres connection


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:1000]


def _call(fn, args: tuple, timeout: float):
    """Run fn in a daemon thread; a hung collector is abandoned, not awaited."""
    box = {}

    def target():
        try:
            box["result"] = fn(*args)
        except BaseException as exc:  # handed back to the caller below
            box["error"] = exc

    thread = threading.Thread(target=target, name=f"collect-{getattr(fn, '__module__', '')}", daemon=True)
    thread.start()
    thread.join(max(0.0, timeout))
    if thread.is_alive():
        raise TimeoutError(f"exceeded {timeout:g}s source timeout")
    if "error" in box:
        raise box["error"]
    return box["result"]


def _process(cid: str, meta: dict, events: list) -> list[tuple[Event, Event]]:
    fetched = utcnow()
    pairs = []
    for item in events or []:
        raw = Event.model_validate(item).model_copy(update={"source": cid, "fetched_at": fetched})
        event = store.clean(classify(raw, meta))
        if not store.is_junk(event):
            pairs.append((raw, event))
    return pairs


def _plan(module: ModuleType, pass_name: str) -> list[str]:
    if callable(getattr(module, "scopes", None)) and callable(getattr(module, "collect_scope", None)):
        return list(module.scopes(pass_name))
    return ["*"]


def crawl_source(cid: str, module: ModuleType, pass_name: str, timeout: float) -> dict:
    """Crawl every scope of one source. Collector failures are returned, DB failures raise."""
    meta = {**module.SOURCE, "id": cid}
    started = utcnow()
    clock = time.monotonic()
    deadline = clock + timeout
    try:
        scope_keys = _plan(module, pass_name)
    except Exception as exc:
        scope_keys, plan_error = [], _error(exc)
    else:
        plan_error = None
    scoped = scope_keys != ["*"]
    limit = getattr(module, "SCOPE_LIMIT", None)
    errors, ok_scopes, total = [plan_error] if plan_error else [], 0, 0
    for scope in scope_keys:
        scope_started = utcnow()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            errors.append(f"TimeoutError: source timeout before scope {scope}")
            break
        try:
            fn, args = (module.collect_scope, (scope,)) if scoped else (module.collect, ())
            pairs = _process(cid, meta, _call(fn, args, remaining))
            error = None
        except Exception as exc:
            pairs, error = [], _error(exc)
        finished = utcnow()
        saturated = getattr(module, "RANKED_SEARCH", False) or (bool(limit) and len(pairs) >= limit)
        with _db_lock, db.connect() as conn:
            exhaustive = False
            if error is None:
                previous = store.active_count(conn, cid, scope)
                count = store.upsert_sources(conn, cid, scope, pairs, scope_started)
                # Zero rows where we had some smells like a parser break, not an empty listing.
                exhaustive = not saturated and not (count == 0 and previous > 0)
                if exhaustive:
                    store.mark_misses(conn, cid, scope, scope_started)
            if scoped:
                store.record_scope(conn, cid, scope, crawled_at=finished, count=len(pairs),
                                   saturated=saturated, error=error)
            store.record_run(conn, pass_name=pass_name, source=cid, scope_key=scope, started_at=scope_started,
                             finished_at=finished, status="ok" if error is None else "error",
                             rows=len(pairs), exhaustive=exhaustive, error=error)
        if error is None:
            ok_scopes += 1
            total += len(pairs)
        else:
            errors.append(error if not scoped else f"{scope}: {error}")
            log.warning("%s %s failed: %s", cid, scope, error)
    status = "ok" if not errors else "partial" if ok_scopes else "error"
    error = "; ".join(errors)[:1000] if errors else None
    backoff = utcnow() + BLOCK_BACKOFF if error and not ok_scopes and _BLOCKED.search(error) else None
    with _db_lock, db.connect() as conn:
        store.record_source(conn, cid, ran_at=started, ok=ok_scopes > 0, error=error, count=total,
                            duration_ms=int((time.monotonic() - clock) * 1000), backoff_until=backoff)
    log.info("%s: %s, %d rows from %d/%d scopes in %.1fs", cid, status, total, ok_scopes,
             len(scope_keys), time.monotonic() - clock)
    return {"id": cid, "status": status, "rows": total, "error": error}


def _backed_off(conn: db.Connection, cid: str, now: datetime) -> bool:
    row = conn.fetchone("SELECT backoff_until FROM sources WHERE id = ?", (cid,))
    return bool(row and row["backoff_until"] and row["backoff_until"] > store.iso(now))


def load() -> dict[str, ModuleType]:
    """Import every collector; a broken module is logged and skipped, not fatal."""
    from .collectors import COLLECTOR_IDS

    mods = {}
    for cid in COLLECTOR_IDS:
        try:
            mods[cid] = importlib.import_module(f"hackfinder.collectors.{cid}")
        except Exception:
            log.exception("Could not import collector %s", cid)
    return mods


def refresh_rates() -> None:
    """Fetch one ECB reference table per run; preserve the last good table offline."""
    import httpx
    from xml.etree import ElementTree
    from .score import STATIC_RATES

    try:
        response = httpx.get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml", timeout=10)
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        rates = {node.attrib["currency"]: float(node.attrib["rate"]) for node in root.iter()
                 if "currency" in node.attrib and "rate" in node.attrib}
        if "USD" not in rates or any(value <= 0 for value in rates.values()):
            raise ValueError("invalid ECB rates")
        rates["EUR"] = 1
        payload = {"rates": rates, "fetched_at": store.iso(utcnow()), "source": "ECB"}
    except Exception as exc:
        log.warning("ECB unavailable; using cached/static rates: %s", exc)
        with db.connect() as conn:
            if conn.fetchone("SELECT key FROM score_cache WHERE key = 'ecb'"):
                return
        payload = {"rates": STATIC_RATES, "fetched_at": None, "source": "static fallback"}
    with db.connect() as conn:
        conn.execute("""INSERT INTO score_cache (key, data) VALUES ('ecb', CAST(? AS JSONTYPE))
                        ON CONFLICT (key) DO UPDATE SET data = excluded.data""", (db.dumps(payload),))


def run(pass_name: str, only: list[str] | None = None, collectors: dict[str, ModuleType] | None = None) -> dict:
    """Run one pass. Raises only on database failure."""
    if pass_name not in PASSES:
        raise ValueError(f"unknown pass {pass_name!r}")
    if collectors is None:
        collectors = load()
    wanted = PASSES[pass_name]
    skip = set(LOCAL_ONLY) if pass_name == "full" and os.getenv("GITHUB_ACTIONS") == "true" and not only else set()
    selected = {cid: mod for cid, mod in collectors.items()
                if (wanted is None or cid in wanted) and (not only or cid in only) and cid not in skip}
    db.init(places=True)
    refresh_rates()
    now = utcnow()
    with db.connect() as conn:
        for cid, module in collectors.items():
            store.register_source(conn, {**module.SOURCE, "id": cid})
        if pass_name not in ("full", "local"):  # full and local passes always retry blocked sources
            for cid in [cid for cid in selected if _backed_off(conn, cid, now)]:
                log.warning("%s skipped: backing off after a block", cid)
                del selected[cid]
    timeout = SOURCE_TIMEOUT[pass_name]
    results = []
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL, thread_name_prefix="source") as pool:
        futures = [pool.submit(crawl_source, cid, module, pass_name, timeout) for cid, module in selected.items()]
        for future in futures:
            results.append(future.result())  # a DB error propagates here
    with _db_lock, db.connect() as conn:
        total = store.remerge(conn)
    return {"pass": pass_name, "sources": results, "events": total}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hackfinder.worker", description=__doc__.splitlines()[0])
    parser.add_argument("--pass", dest="pass_name", choices=sorted(PASSES), required=True)
    parser.add_argument("--only", default="", help="comma-separated source ids")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    db.configure(1)
    only = [x.strip() for x in args.only.split(",") if x.strip()] or None
    try:
        summary = run(args.pass_name, only)
    except Exception:
        log.exception("Worker failed")
        return 1
    finally:
        db.close()
    failed = [s for s in summary["sources"] if s["status"] != "ok"]
    for source in failed:
        log.warning("%s %s: %s", source["id"], source["status"], source["error"])
    log.info("Pass %s done: %d sources, %d failed, %d active events", summary["pass"],
             len(summary["sources"]), len(failed), summary["events"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
