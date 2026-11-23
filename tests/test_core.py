"""Offline regression checks: python tests/test_core.py (no pytest required).

Every test uses a temporary SQLite database; DATABASE_URL is ignored.
"""
from __future__ import annotations

from datetime import timedelta
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_GEOCODE_ONLINE", "0")  # no network in tests
os.environ.pop("DATABASE_URL", None)

from fastapi.testclient import TestClient
from hackfinder import db, store, worker
from hackfinder.classify import classify
from hackfinder.dedupe import dedupe, normalize_url
from hackfinder.models import Event
from hackfinder.store import utcnow

app_module = importlib.import_module("hackfinder.app")



def event(title="AI Build Night", **kwargs):
    return Event(**{"source": "luma", "url": "https://luma.com/test", "title": title, **kwargs})


def test_classification():
    mixed = {"default_kind": "mixed"}
    cases = {
        "AI Build Night": "hackathon", "Data datathon": "hackathon",
        "Hack day": "hackathon", "Buildathon": "hackathon", "Makeathon": "hackathon",
        "Student hackaton": "hackathon", "Hakaton": "hackathon",
        "ハッカソン": "hackathon", "해커톤": "hackathon", "黑客松": "hackathon",
        "Хакатон": "hackathon", "هاكاثون": "hackathon",
        "Game Jam": "game_jam", "Community Jam": "unknown",  # bare "jam" needs a game cue (music/comedy jams exist)
        "Capture the flag": "ctf", "CTF finals": "ctf", "Ideathon": "ideathon",
        "Coding competition": "coding_competition",
        "Info session about the hackathon": "info_session", "Hackathon workshop": "workshop",
        "AI meetup": "meetup", "Hackathon webinar": "talk", "Local gathering": "unknown",
    }
    for title, kind in cases.items():
        result = classify(event(title), mixed)
        assert result.kind == kind, (title, result.kind, kind)
    hinted = classify(event("Workshop", kind="ctf", classified_by="source", confidence=.95), mixed)
    assert hinted.kind == "ctf" and hinted.confidence == .95
    default = classify(event("Mystery"), {"default_kind": "hackathon"})
    assert (default.kind, default.confidence, default.classified_by) == ("hackathon", .9, "source")
    tagged = classify(event("AI web3 student civic robotics hackathon"), mixed)
    assert set(tagged.tags) == {"ai", "web3", "student", "gov", "hardware"}
    original = event("AI hackathon", tags=["custom"])
    assert classify(original, mixed).tags == ["custom"] and original.kind == "unknown"
    assert classify(event("Workshop: build a project together"), mixed).kind == "hackathon"
    print("PASS classification")


def test_dedupe():
    assert normalize_url("http://www.lu.ma/abc/?utm_source=foo&b=2&a=1#hi") == "https://luma.com/abc?a=1&b=2"
    now = utcnow()
    aggregator = event("AI Hackathon 2027", start=now, participants=120, description="Useful detail")
    aggregator.source = "hackathoncom"
    official = event("2027 AI Hackathon", start=now + timedelta(days=1))
    official.source = "devpost"
    official.url = "https://devpost.com/event"
    merged = dedupe([aggregator, official])
    assert len(merged) == 1 and merged[0].source == "devpost"
    assert merged[0].participants == 120 and merged[0].description == "Useful detail"
    assert merged[0].also_on == ["hackathoncom"]
    branded = official.model_copy(update={"title": "2027 AI Hackathon by Devpost", "url": "https://another.com/event"})
    assert len(dedupe([official, branded])) == 1
    assert len(dedupe([official, official.model_copy(update={"source": "luma", "url": official.url + "?utm_campaign=x"})])) == 1
    for changes in ({"start": now + timedelta(days=5)}, {"title": "2028 AI Hackathon"},
                    {"location": "Berlin"}):
        other = official.model_copy(update={"url": "https://other.com/event", **changes})
        first = official.model_copy(update={"location": "Paris"}) if "location" in changes else official
        assert len(dedupe([first, other])) == 2
    assert len(dedupe([event("Same"), event("Same").model_copy(update={"url": "https://different.com"})])) == 2
    assert aggregator.also_on == []
    print("PASS dedupe")


def collector(cid, collect, **extra):
    return SimpleNamespace(SOURCE={"id": cid, "name": cid.title(), "method": "api", "default_kind": "mixed"},
                           collect=collect, **extra)


def fresh_db(directory):
    os.environ["HF_DB_PATH"] = str(Path(directory) / "test.db")
    db.init()
    app_module.clear_cache()


def source_rows(where="1 = 1", params=()):
    with db.connect() as conn:
        return {r["ident"]: r for r in conn.fetchall(f"SELECT * FROM event_sources WHERE {where}", params)}


def test_store():
    now = utcnow()
    with tempfile.TemporaryDirectory() as directory:
        fresh_db(directory)
        a = event("AI Hackathon 2027", source="meetup", url="https://meetup.com/a", source_id="a", start=now + timedelta(days=3))
        b = event("2027 AI Hackathon", source="devpost", url="https://devpost.com/a", start=now + timedelta(days=3),
                  participants=50)
        c = event("Robotics Hackathon", source="devpost", url="https://devpost.com/c", start=now + timedelta(days=9))
        old = event("Past Hackathon", source="devpost", url="https://devpost.com/old",
                    start=now - timedelta(days=9), end=now - timedelta(days=8))
        with db.connect() as conn:
            assert store.upsert_sources(conn, "meetup", "*", [(a, a), (a, a)], now) == 1
            store.upsert_sources(conn, "devpost", "*", [(e, e) for e in (b, c, old)], now)
            assert store.remerge(conn, now) == 2
            rows = {r["key"]: r for r in conn.fetchall("SELECT * FROM events")}
        assert rows["https://devpost.com/a"]["status"] == "active"
        merged = db.loads(rows["https://devpost.com/a"]["data"])
        assert merged["also_on"] == ["meetup"] and merged["participants"] == 50
        assert set(rows) == {"https://devpost.com/a", "https://devpost.com/c"}
        later = now + timedelta(hours=1)
        changed = a.model_copy(update={"title": "AI Hackathon 2027 (updated)"})
        with db.connect() as conn:
            store.upsert_sources(conn, "meetup", "*", [(changed, changed)], later)
        row = source_rows()["id:a"]
        assert row["first_seen"] == store.iso(now) and row["last_seen"] == store.iso(later)
        assert db.loads(row["data"])["title"] == changed.title
        assert store.clean(event("x", prize="$0", prize_usd=0)).prize is None
        assert store.clean(event("x", prize="$5,000")).prize == "$5,000"
        assert store.is_junk(event("Test 2")) and not store.is_junk(event("Testing Hackathon"))
    print("PASS store upsert, merge and dedupe")


def test_lifecycle():
    now = utcnow()
    keep = event("Kept Hackathon", url="https://luma.com/keep", start=now + timedelta(days=2))
    drop = event("Dropped Hackathon", url="https://luma.com/drop", start=now + timedelta(days=2))
    with tempfile.TemporaryDirectory() as directory:
        fresh_db(directory)
        listing = [keep, drop]
        registry = {"luma": collector("luma", lambda: list(listing))}
        worker.run("quick", collectors=registry)
        listing.remove(drop)
        worker.run("quick", collectors=registry)
        assert source_rows()["url:https://luma.com/drop"]["miss_count"] == 1
        assert source_rows()["url:https://luma.com/drop"]["active"]
        # A failed run changes nothing.
        registry["luma"] = collector("luma", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
        assert worker.run("quick", collectors=registry)["sources"][0]["status"] == "error"
        assert source_rows()["url:https://luma.com/drop"]["miss_count"] == 1
        # An empty result where rows existed is treated as broken, not exhaustive.
        registry["luma"] = collector("luma", lambda: [])
        worker.run("quick", collectors=registry)
        assert source_rows()["url:https://luma.com/drop"]["miss_count"] == 1
        registry["luma"] = collector("luma", lambda: list(listing))
        worker.run("quick", collectors=registry)
        rows = source_rows()
        assert not rows["url:https://luma.com/drop"]["active"] and rows["url:https://luma.com/keep"]["active"]
        with db.connect() as conn:
            status = {r["key"]: r["status"] for r in conn.fetchall("SELECT key, status FROM events")}
            runs = conn.fetchall("SELECT status, exhaustive FROM crawl_runs ORDER BY id")
        assert status == {"https://luma.com/keep": "active", "https://luma.com/drop": "missing"}
        assert [(r["status"], bool(r["exhaustive"])) for r in runs] == [
            ("ok", True), ("ok", True), ("error", False), ("ok", False), ("ok", True)]
        # A reappearing listing is active again with its original first_seen.
        listing.append(drop)
        worker.run("quick", collectors=registry)
        row = source_rows()["url:https://luma.com/drop"]
        assert row["active"] and row["miss_count"] == 0
    print("PASS lifecycle: 2 exhaustive misses, failed/empty runs change nothing")


def test_worker():
    now = utcnow()
    calls = []

    def scopes(pass_name):
        return ["global"] if pass_name == "quick" else ["global", "place:amsterdam", "place:broken"]

    def collect_scope(scope):
        calls.append(scope)
        if scope == "place:broken":
            raise RuntimeError("HTTP 500")
        return [event(f"{scope} hackathon", url=f"https://luma.com/{scope.replace(':', '-')}",
                      start=now + timedelta(days=1))]

    def slow():
        time.sleep(2)
        return [event("Late", url="https://devpost.com/late")]

    registry = {
        "luma": collector("luma", lambda: [], scopes=scopes, collect_scope=collect_scope),
        "devpost": collector("devpost", lambda: [event("Devpost Hackathon", source="x", url="https://devpost.com/h",
                                                       start=now + timedelta(days=4))]),
        "kaggle": collector("kaggle", slow),
        "meetup": collector("meetup", lambda: (_ for _ in ()).throw(AssertionError("not in quick"))),
    }
    with tempfile.TemporaryDirectory() as directory:
        fresh_db(directory)
        summary = worker.run("quick", collectors=registry)
        assert calls == ["global"] and {s["id"] for s in summary["sources"]} == {"luma", "devpost"}
        assert source_rows("source = ?", ("devpost",))["url:https://devpost.com/h"]["scope_key"] == "*"
        with patch.dict(worker.SOURCE_TIMEOUT, {"full": .2}):
            before = time.monotonic()
            summary = worker.run("full", only=["luma", "kaggle"], collectors=registry)
            assert time.monotonic() - before < 1.5
        status = {s["id"]: s for s in summary["sources"]}
        assert status["luma"]["status"] == "partial" and "place:broken" in status["luma"]["error"]
        assert status["kaggle"]["status"] == "error" and "TimeoutError" in status["kaggle"]["error"]
        assert summary["events"] == 3
        with db.connect() as conn:
            scope_rows = {r["scope_key"]: r for r in conn.fetchall("SELECT * FROM scopes WHERE source = 'luma'")}
            sources = {r["id"]: r for r in conn.fetchall("SELECT * FROM sources")}
        assert set(scope_rows) == {"global", "place:amsterdam", "place:broken"}
        assert scope_rows["place:broken"]["last_error"] and scope_rows["global"]["last_count"] == 1
        assert sources["meetup"]["last_run_at"] is None and sources["kaggle"]["last_error"]
        assert sources["luma"]["last_success_at"] and sources["devpost"]["last_count"] == 1
        assert worker.main(["--pass", "quick", "--only", "nothing"]) == 0
    print("PASS worker: plain and scoped collectors, partial runs, timeouts, pass selection")


def test_app():
    now = utcnow()
    future = now + timedelta(hours=24)
    rows = [
        event("AI Build Night", start=future, end=future + timedelta(days=1), format="online", prize_usd=1000,
              participants=10, registration_deadline=future),
        event("Mystery Hackathon", url="https://luma.com/unknown", format="hybrid", participants=40),
        event("Past Hackathon", url="https://luma.com/past", start=now - timedelta(days=10), end=now - timedelta(days=9)),
        event("Game Jam", url="https://luma.com/jam", start=future),
        event("Future Hackathon", url="https://luma.com/later", start=now + timedelta(days=40), prize_usd=2000),
        event("Ongoing Hackathon", url="https://luma.com/ongoing", start=now - timedelta(days=2), end=now + timedelta(days=1)),
        event("Soon 100% Hackathon", url="https://luma.com/soon", start=now + timedelta(hours=2)),
        event("Info session about the hackathon", url="https://luma.com/session", start=future),
    ]
    with tempfile.TemporaryDirectory() as directory:
        fresh_db(directory)
        worker.run("quick", collectors={"luma": collector("luma", lambda: rows)})
        with TestClient(app_module.app) as client:
            response = client.get("/api/hackathons")
            assert response.headers["cache-control"] == "public, s-maxage=60, stale-while-revalidate=300"
            result = response.json()
            titles = [e["title"] for e in result["events"]]
            assert titles == ["Soon 100% Hackathon", "AI Build Night", "Future Hackathon", "Ongoing Hackathon",
                              "Mystery Hackathon"], titles
            assert result["total"] == 5 and result["page"] == 1 and result["per_page"] == 100
            assert result["events"][0]["first_seen"] and result["events"][0]["last_seen"]
            assert all(isinstance(e["categories"], list) and isinstance(e["flags"], list) for e in result["events"])
            assert "ai" in {c for e in result["events"] if e["title"] == "AI Build Night" for c in e["categories"]}
            assert result["updated_at"] and result["sources"][0]["id"] == "luma"
            desc = [e["title"] for e in client.get("/api/hackathons?order=desc").json()["events"]]
            assert desc == ["Future Hackathon", "AI Build Night", "Soon 100% Hackathon", "Ongoing Hackathon",
                            "Mystery Hackathon"], desc
            paged = client.get("/api/hackathons?per_page=2&page=2").json()
            assert [e["title"] for e in paged["events"]] == ["Future Hackathon", "Ongoing Hackathon"]
            assert paged["total"] == 5 and paged["page"] == 2
            assert client.get("/api/hackathons?kinds=game_jam").json()["total"] == 1
            assert client.get("/api/hackathons?kinds=other,unknown").json()["total"] == 0
            assert client.get("/api/hackathons?format=online&q=BUILD&days=7").json()["total"] == 1
            assert client.get("/api/hackathons?q=100%25").json()["total"] == 1
            assert client.get("/api/hackathons?q=_").json()["total"] == 0
            assert client.get("/api/hackathons?days=30").json()["total"] == 4
            assert client.get("/api/hackathons?sort=prize&order=desc").json()["events"][0]["prize_usd"] == 2000
            assert client.get("/api/hackathons?sort=prize").json()["events"][0]["prize_usd"] == 1000
            assert client.get("/api/hackathons?sort=participants&order=desc").json()["events"][0]["participants"] == 40
            assert client.get("/api/hackathons?days=invalid").status_code == 422
            assert client.get("/api/hackathons?per_page=501").status_code == 422
            stats = client.get("/api/stats")
            assert stats.headers["cache-control"].startswith("public, s-maxage=60")
            stats = stats.json()
            assert stats["total"] == 5 and stats["start_48h"] == 2 and stats["open_now"] == 2, stats
            assert stats["new_this_week"] == 5 and stats["sources"] == 1 and stats["updated_at"]
            sources = client.get("/api/sources").json()
            assert sources[0]["status"] == "ok" and sources[0]["count"] == len(rows), sources
            assert set(sources[0]) >= {"id", "name", "method", "status", "count", "last_success_at", "last_run_at", "error"}
            assert client.get("/api/stream").status_code == 404
            # Responses are cached in-process for 30 s.
            with db.connect() as conn:
                conn.execute("DELETE FROM events")
            assert client.get("/api/hackathons").json()["total"] == 5
            app_module.clear_cache()
            assert client.get("/api/hackathons").json()["total"] == 0
            assert client.get("/").status_code == 200 and client.get("/hackathons").status_code == 200
    print("PASS app API filters, starting-soonest order, paging, stats, sources, caching")


def test_app_imports():
    code = ("import sys, hackfinder.app; bad = [m for m in sys.modules if m.split('.')[0] in "
            "{'seleniumbase', 'playwright', 'httpx', 'selectolax', 'geonamescache'} or m.startswith('hackfinder.collectors')]; "
            "print(bad); sys.exit(1 if bad else 0)")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    print("PASS web app imports no collectors or scraping libraries")


if __name__ == "__main__":
    os.environ.pop("DATABASE_URL", None)
    patch("hackfinder.worker.refresh_rates").start()
    test_classification()
    test_dedupe()
    test_store()
    test_lifecycle()
    test_worker()
    test_app()
    test_app_imports()
    print("All core tests passed (offline).")
