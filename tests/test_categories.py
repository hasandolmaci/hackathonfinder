"""Offline category/flag checks: python tests/test_categories.py (no pytest required)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("DATABASE_URL", None)

from fastapi.testclient import TestClient
from hackfinder import db, store, worker
from hackfinder.categories import CATEGORIES, TYPES, categorize, flags, pack, unpack
from hackfinder.models import Event

app_module = importlib.import_module("hackfinder.app")


def event(title="Build Night", **kwargs):
    return Event(**{"source": "luma", "url": "https://luma.com/" + title.replace(" ", "-"), "title": title,
                    "kind": "hackathon", **kwargs})


def test_categories():
    cases = [
        (event("AI Build Night"), ["ai"]),
        (event("Web3 Builders Hackathon"), ["web3"]),
        (event("Hack the Future", tags=["Machine Learning/AI", "Health"]), {"ai", "health"}),
        (event("City Hack", description="Build tools for climate resilience and clean energy."), ["climate"]),
        (event("Robotics Hackathon"), {"robotics"}),
        (event("Mobile App Hackathon"), ["mobile"]),
        (event("Fintech Challenge"), ["fintech"]),
        (event("Open Source Sprint"), ["opensource"]),
        (event("Space Apps Challenge"), ["space"]),
        (event("Hack", signals={"themes": ["Cybersecurity", "Gaming"]}), {"security", "gaming"}),
        (event("Jam", kind="game_jam"), ["gaming"]),
        (event("Weekend Contest", kind="ctf"), ["security"]),
        (event("Mystery Hack", source="ethglobal"), ["web3"]),
        (event("Mystery Hack", source="kaggle"), ["data"]),
        (event("Mystery Hack", source="dorahacks"), ["web3"]),
        # guards: no keyword, or keyword only inside another word
        (event("Spring Hackathon"), []),
        (event("Maintain the Chair: said the waiter, paid in full", description="Rails and trains wait; air and fair."), []),
        (event("The Hackathon of Paid Daily Tasks"), []),
        # "game" idioms are not gaming
        (event("Game Changer Hackathon"), []),
        (event("Hackathon", description="A game-changing weekend and a game plan for founders."), []),
        (event("Game Jam Weekend"), ["gaming"]),
        (event("Video Game Hackathon"), ["gaming"]),
        # RPA is not robotics; "machine learning" is not education
        (event("Hack", tags=["Robotic Process Automation"]), ["devtools"]),
        (event("Hack", tags=["Machine Learning/AI"]), ["ai"]),
        # one mention in the long source text is not enough, repeated mentions are
        (event("Hack Day", signals={"text": "Sponsors include AWS."}), []),
        (event("Hack Day", signals={"text": "Use AWS Lambda. Deploy on AWS. AWS credits."}), ["cloud"]),
    ]
    for ev, expected in cases:
        got = categorize(ev)
        assert (set(got) == set(expected) if isinstance(expected, set) else got == expected), (ev.title, got, expected)
        assert all(c in CATEGORIES for c in got)
    many = event("AI web3 health climate robotics gaming hackathon")
    assert len(categorize(many)) == 4
    assert unpack(pack(["ai", "web3"])) == ["ai", "web3"] and pack([]) == "," and unpack(",") == []
    print("PASS categories: keywords, word boundaries, source hints, idiom guards, cap")


def test_flags():
    start = datetime(2027, 1, 8, 18, tzinfo=timezone.utc)  # a Friday
    assert start.weekday() == 4
    assert flags(event("Hack", source="mlh")) == ["student"]
    assert "student" in flags(event("University Hackathon"))
    assert "student" in flags(event("Hack", description="Open to all high school students."))
    assert "student" not in flags(event("Hack", description="Students and professionals are welcome to build."))
    assert "student" in flags(event("Hack", signals={"students_only": True}))
    assert "beginner" in flags(event("Hack", signals={"themes": ["Beginner Friendly"]}))
    assert "beginner" in flags(event("Hack", description="First-timers welcome, no experience needed."))
    assert "beginner" not in flags(event("Hack", description="Not for beginners; advanced hackers only."))
    assert "cash_prize" in flags(event("Hack", prize_usd=500))
    assert "cash_prize" in flags(event("Hack", signals={"prize_amount": 1000, "prize_currency": "EUR"}))
    assert "cash_prize" not in flags(event("Hack", signals={"prize_amount": 1000, "prize_noncash": True}))
    assert "cash_prize" not in flags(event("Hack", prize_usd=0))
    assert "travel" in flags(event("Hack", signals={"travel_support": True}))
    assert "travel" in flags(event("Hack", description="We offer travel reimbursement for finalists."))
    assert "travel" not in flags(event("Hack", description="Sorry, no travel reimbursement."))
    assert "weekend" in flags(event("Hack", format="in-person", start=start, end=start + timedelta(days=2)))
    assert "weekend" in flags(event("Hack", format="hybrid", start=start + timedelta(days=1)))
    assert "weekend" not in flags(event("Hack", format="online", start=start, end=start + timedelta(days=2)))
    assert "weekend" not in flags(event("Hack", format="in-person", start=start + timedelta(days=3)))  # Monday
    assert "weekend" not in flags(event("Hack", format="in-person", start=start, end=start + timedelta(days=9)))
    assert flags(event("Plain")) == []
    print("PASS flags: student, beginner, cash_prize, travel, weekend")


def collector(cid, rows):
    return SimpleNamespace(SOURCE={"id": cid, "name": cid.title(), "method": "api", "default_kind": "mixed"},
                           collect=lambda: rows)


def test_foryou_points():
    f = app_module._foryou
    assert f({"score": 50, "cats": ",ai,"}, ("ai",)) == 62
    assert f({"score": 50, "cats": ",ai,climate,web,"}, ("ai", "climate", "web")) == 74  # capped at +24
    assert f({"score": None, "cats": ","}, ("ai",)) == 45
    assert f({"score": None, "cats": ",ai,"}, ("ai",)) == 57
    assert f({"score": 80, "cats": ","}, ()) == 80
    print("PASS foryou points: +12 per interest, capped at +24, unknown score counts 45")


def test_api():
    now = store.utcnow()
    soon = now + timedelta(days=3)
    friday = soon + timedelta(days=(4 - soon.weekday()) % 7 or 7)
    rows = [
        event("AI Health Hackathon", start=soon, end=soon + timedelta(days=5), prize_usd=1000, format="online"),
        event("Climate Student Hackathon", start=soon + timedelta(days=1), end=soon + timedelta(days=2), format="online"),
        event("Web3 Weekend Hackathon", start=friday, end=friday + timedelta(days=2), format="in-person",
              location="Berlin, Germany", signals={"travel_support": True}),
        event("Plain Hackathon", start=soon + timedelta(days=2), end=soon + timedelta(days=3), format="online"),
        event("Beginner Robotics Hackathon", start=soon + timedelta(days=4), end=soon + timedelta(days=5),
              format="online", signals={"themes": ["Beginner Friendly"]}),
        event("Old AI Hackathon", start=now - timedelta(days=9), end=now - timedelta(days=8)),
    ]
    with tempfile.TemporaryDirectory() as directory:
        os.environ["HF_DB_PATH"] = str(Path(directory) / "test.db")
        db.init()
        app_module.clear_cache()
        with patch("hackfinder.worker.refresh_rates"):
            worker.run("quick", collectors={"luma": collector("luma", rows)})
        with TestClient(app_module.app) as client:
            def titles(query):
                return [e["title"] for e in client.get("/api/hackathons?" + query).json()["events"]]

            everything = client.get("/api/hackathons").json()["events"]
            assert len(everything) == 5
            by_title = {e["title"]: e for e in everything}
            assert set(by_title["AI Health Hackathon"]["categories"]) == {"ai", "health"}
            assert by_title["Plain Hackathon"]["categories"] == [] and "new" in by_title["Plain Hackathon"]["flags"]
            assert {"travel", "weekend", "new"} <= set(by_title["Web3 Weekend Hackathon"]["flags"])
            assert "student" in by_title["Climate Student Hackathon"]["flags"]
            assert "cash_prize" in by_title["AI Health Hackathon"]["flags"]
            # categories: match ANY; unknown ids ignored
            assert titles("categories=ai") == ["AI Health Hackathon"]
            assert sorted(titles("categories=ai,climate")) == ["AI Health Hackathon", "Climate Student Hackathon"]
            assert titles("categories=health,nonsense") == ["AI Health Hackathon"]
            assert titles("categories=nonsense") == titles("")
            # types: match ALL
            assert titles("types=student") == ["Climate Student Hackathon"]
            assert titles("types=weekend,travel") == ["Web3 Weekend Hackathon"]
            assert titles("types=student,travel") == []
            assert titles("types=beginner") == ["Beginner Robotics Hackathon"]
            assert len(titles("types=new")) == 5
            assert titles("types=cash_prize&categories=ai") == ["AI Health Hackathon"]
            # "new" is computed from first_seen at query time
            with db.connect() as conn:
                conn.execute("UPDATE events SET first_seen = ? WHERE title = ?",
                             (store.iso(now - timedelta(days=30)), "Plain Hackathon"))
            app_module.clear_cache()
            assert "Plain Hackathon" not in titles("types=new") and len(titles("types=new")) == 4
            plain = next(e for e in client.get("/api/hackathons").json()["events"] if e["title"] == "Plain Hackathon")
            assert "new" not in plain["flags"]
            # foryou: score + 12 per matched interest (max +24), unknown score = 45, ties by start date
            with db.connect() as conn:
                for title, value in {"AI Health Hackathon": 50, "Climate Student Hackathon": 60,
                                     "Web3 Weekend Hackathon": 70, "Beginner Robotics Hackathon": 40,
                                     "Plain Hackathon": None}.items():
                    conn.execute("UPDATE events SET score = ? WHERE title = ?", (value, title))
            app_module.clear_cache()
            assert titles("sort=foryou") == ["Web3 Weekend Hackathon", "Climate Student Hackathon", "AI Health Hackathon",
                                             "Plain Hackathon", "Beginner Robotics Hackathon"]
            # ai+health = 50 + 24 = 74 beats web3 70 and climate 60
            assert titles("sort=foryou&interests=ai,health") == [
                "AI Health Hackathon", "Web3 Weekend Hackathon", "Climate Student Hackathon", "Plain Hackathon",
                "Beginner Robotics Hackathon"]
            # one interest: 50 + 12 = 62 sits between web3 70 and climate 60
            assert titles("sort=foryou&interests=ai") == [
                "Web3 Weekend Hackathon", "AI Health Hackathon", "Climate Student Hackathon", "Plain Hackathon",
                "Beginner Robotics Hackathon"]
            # robotics interest lifts 40 to 52: past unknown (45) and ai (50), below climate (60)
            assert titles("sort=foryou&interests=robotics") == [
                "Web3 Weekend Hackathon", "Climate Student Hackathon", "Beginner Robotics Hackathon",
                "AI Health Hackathon", "Plain Hackathon"]
            assert titles("sort=foryou&interests=ai&per_page=2&page=2") == ["Climate Student Hackathon", "Plain Hackathon"]
            # /api/categories
            response = client.get("/api/categories?kinds=hackathon")
            assert response.headers["cache-control"].startswith("public, s-maxage=60")
            body = response.json()
            counts = {c["id"]: c["count"] for c in body["categories"]}
            assert set(counts) == set(CATEGORIES) and counts["ai"] == 1 and counts["health"] == 1
            assert counts["climate"] == 1 and counts["web3"] == 1 and counts["robotics"] == 1 and counts["gaming"] == 0
            assert [c["count"] for c in body["categories"]] == sorted((c["count"] for c in body["categories"]), reverse=True)
            assert next(c for c in body["categories"] if c["id"] == "ai")["name"] == "AI & ML"
            types = {t["id"]: t["count"] for t in body["types"]}
            assert list(types) == list(TYPES)
            assert types == {"student": 1, "beginner": 1, "cash_prize": 1, "travel": 1, "weekend": 1, "new": 4}, types
            assert sum(c["count"] for c in client.get("/api/categories?kinds=game_jam").json()["categories"]) == 0
            assert client.get("/api/categories?days=bad").status_code == 422
            assert client.get("/api/hackathons?sort=bogus").status_code == 422
        # rows without cats/flags (before the first rescore) still get them from the event data
        with db.connect() as conn:
            conn.execute("UPDATE events SET cats = NULL, flags = NULL")
        app_module.clear_cache()
        with TestClient(app_module.app) as client:
            fallback = {e["title"]: e for e in client.get("/api/hackathons").json()["events"]}
            assert set(fallback["AI Health Hackathon"]["categories"]) == {"ai", "health"}
    print("PASS API: categories/types filters, new flag, sort=foryou, /api/categories counts, NULL fallback")


def test_migration_and_rescore():
    with tempfile.TemporaryDirectory() as directory:
        os.environ["HF_DB_PATH"] = str(Path(directory) / "old.db")
        with db.connect() as conn:  # an old database without cats/flags
            conn.execute("CREATE TABLE events (key TEXT PRIMARY KEY, data TEXT NOT NULL, source TEXT NOT NULL, "
                         "kind TEXT NOT NULL, format TEXT NOT NULL, title TEXT NOT NULL, search TEXT NOT NULL, "
                         "start_at TEXT, end_at TEXT, deadline_at TEXT, prize_usd REAL, participants INTEGER, "
                         "first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', "
                         "updated_at TEXT NOT NULL)")
        db.init()
        db.init()  # idempotent
        with db.connect() as conn:
            names = {r["name"] for r in conn.fetchall("PRAGMA table_info(events)")}
            assert {"cats", "flags", "score", "lat"} <= names
            ev = event("AI Hackathon", prize_usd=100)
            stamp = store.iso(store.utcnow())
            conn.execute("INSERT INTO events (key, data, source, kind, format, title, search, first_seen, last_seen, "
                         "status, updated_at) VALUES (?, ?, 'luma', 'hackathon', 'online', ?, ?, ?, ?, 'active', ?)",
                         ("k1", db.dumps(ev.model_dump(mode="json")), ev.title, "ai hackathon", stamp, stamp, stamp))
            store.rescore(conn)
            row = conn.fetchone("SELECT data, cats, flags FROM events WHERE key = 'k1'")
            assert row["cats"] == ",ai," and row["flags"] == ",cash_prize,"
            data = db.loads(row["data"])
            assert data["categories"] == ["ai"] and data["flags"] == ["cash_prize"]
    print("PASS idempotent cats/flags migration and rescore backfill")


if __name__ == "__main__":
    test_categories()
    test_flags()
    test_foryou_points()
    test_api()
    test_migration_and_rescore()
    print("All category tests passed (offline).")
