"""Offline parser tests for the HackQuest, DoraHacks, Commudle, Hack Junction, Encode Club and WeMakeDevs collectors.

Run: python tests/test_new_sources_b.py
Fixtures live in tests/fixtures/<source>/ (trimmed live responses; open events are dated 2098-2099).
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackfinder.collectors import commudle, dorahacks, encodeclub, hackjunction, hackquest, wemakedevs

FIX = ROOT / "tests" / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def check(events, n):
    assert len(events) == n, [e.title for e in events]
    assert len({e.url for e in events}) == len(events)
    for e in events:
        assert e.title.strip() and e.url.startswith("https://")
        assert e.kind == "hackathon" and e.confidence == 0.9 and e.classified_by == "source"
        for value in (e.start, e.end, e.registration_deadline):
            assert value is None or value.utcoffset() == timedelta(0)
        if e.format == "online":
            assert e.location is None


def test_hackquest():
    rows = load("hackquest/list.json")["data"]["listHackathons"]["data"]
    events = [e for e in map(hackquest._event, rows) if e]
    check(events, 1)
    e = events[0]
    assert e.url == "https://www.hackquest.io/hackathons/" + rows[0]["alias"]
    assert e.start == datetime(2098, 1, 15, tzinfo=timezone.utc) and e.registration_deadline.year == 2098
    assert e.format == "online" and "web3" in e.tags and e.prize_usd and e.organizer and e.participants is not None


def test_dorahacks():
    data = load("dorahacks/hub.json")
    events = [e for e in (dorahacks._event(r, data["detail"]) for r in data["rows"]) if e]
    assert len(events) == 4  # _event does not filter by date; _collect does.
    live = [e for e in events if e.end >= datetime.now(timezone.utc)]
    check(live, 3)
    virtual, irl, nouname = live
    assert virtual.format == "online" and virtual.prize.endswith("USD") and virtual.prize_usd and "tracks:2" in virtual.tags
    assert virtual.description == "Overview Build things ." and "web3" in virtual.tags
    assert irl.format == "in-person" and irl.url.startswith("https://dorahacks.io/hackathon/")
    assert nouname.url == f"https://dorahacks.io/hackathon/{data['rows'][2]['id']}"  # no uname: page is /hackathon/<id>


def test_commudle():
    rows = [r["data"] for r in load("commudle/future.json")["data"]["page"]]
    events = [e for e in map(commudle._event, rows) if e]
    check(events, 2)
    first = events[0]
    assert first.url == f"https://www.commudle.com/communities/{rows[0]['community']['slug']}/hackathons/{rows[0]['slug']}"
    assert first.format == "hybrid" and first.prize.startswith("INR") and first.prize_usd is None
    assert events[1].format == "in-person" and first.start == datetime(2098, 2, 26, 4, 30, tzinfo=timezone.utc)
    ended = dict(rows[0], end_date="2020-01-01T00:00:00.000+00:00", start_date="2020-01-01T00:00:00.000+00:00")
    assert commudle._event(ended) is None


def test_hackjunction():
    parts = load("hackjunction/trpc.json")
    events = [e for p in parts for r in p["result"]["data"]["json"] for e in [hackjunction._event(r)] if e]
    check(events, 1)
    e = events[0]
    assert e.url == "https://hackjunction.app/hackathons/junction2027-prere" and e.format == "in-person"
    assert e.end == datetime(2098, 11, 14, 18, tzinfo=timezone.utc) and e.organizer == "Junction"


def test_encodeclub():
    rows = load("encodeclub/programmes.json")
    events = [e for e in map(encodeclub._event, rows) if e]
    check(events, 2)  # Hackathon type only: the bootcamp and the ended hackathon are dropped.
    e = {x.title: x for x in events}["Concordium Trusted Agents Hackathon"]
    assert e.url.endswith("/programmes/concordium-trusted-agents-hackathon") and e.format == "online"
    assert e.registration_deadline == datetime(2098, 1, 20, tzinfo=timezone.utc) and e.participants


def test_wemakedevs():
    html = (FIX / "wemakedevs" / "listing.html").read_text(encoding="utf-8")
    cards = wemakedevs._cards(html)
    assert len(cards) == 3
    events = [e for e in map(wemakedevs._event, cards) if e]
    check(events, 2)  # Cloud Native Hackathon (Nov 2026 card) has ended.
    by = {e.title: e for e in events}
    assert by["Festive Hacks"].format == "in-person" and by["Festive Hacks"].location == "BIEC, Bengaluru"
    toggle = by["Toggle Wars"]
    assert toggle.format == "online" and toggle.prize.startswith("$5,000") and toggle.prize_usd == 5000.0
    assert toggle.url == "https://www.wemakedevs.org/hackathons/flagsmith"


if __name__ == "__main__":
    test_hackquest()
    test_dorahacks()
    test_commudle()
    test_hackjunction()
    test_encodeclub()
    test_wemakedevs()
    print("All new-source (b) assertions passed.")
