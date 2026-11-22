"""Offline parser checks for eventbrite, allhackathons, zindi, devnovate, hack2skill, globalgamejam.

Run: .venv\\Scripts\\python tests\\test_new_sources_a.py
Fixtures live in tests/fixtures/<source>/; live dates in them are set far in the future (2099)
so the real-clock "upcoming" filters keep them, and one stale row per source checks the filter.
"""
import json
from datetime import timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackfinder.collectors import allhackathons, devnovate, eventbrite, globalgamejam, hack2skill, zindi

FIX = ROOT / "tests" / "fixtures"


def read(name):
    return (FIX / name).read_text(encoding="utf-8")


def check_fields(events):
    assert len({e.url for e in events}) == len(events)
    for e in events:
        assert e.title.strip() and e.url.startswith("https://")
        for value in (e.start, e.end, e.registration_deadline):
            assert value is None or value.utcoffset() == timedelta(0)
        if e.start and e.end:
            assert e.start <= e.end
        if e.format == "online":
            assert e.location is None


def test_eventbrite():
    events, last, total = eventbrite.parse(read("eventbrite/search.html"))
    check_fields(events)
    by = {e.title: e for e in events}
    assert (last, total) == (3, 5)
    # Networking noise (no hackathon keyword) and the 2020 event are dropped.
    assert set(by) == {"Developer Hackathon", "Cortensor Hackathon #5", "Campus Hack Night"}
    assert all(e.kind == "unknown" for e in events)
    assert by["Developer Hackathon"].format == "online" and by["Developer Hackathon"].country is None
    assert by["Cortensor Hackathon #5"].start.year == 2026 and by["Cortensor Hackathon #5"].end.year == 2099
    camp = by["Campus Hack Night"]
    assert camp.format == "in-person" and camp.country == "US"
    assert camp.location == "AWS Builder Loft, San Francisco, US"
    assert camp.start.hour == 2 and camp.start.day == 5  # 18:00 America/Los_Angeles (PST) -> 02:00Z next day
    assert camp.image == "https://img.evbuc.com/x.jpg" and camp.source_id == "2"
    assert eventbrite.scopes("quick")[0] == "online" and len(eventbrite.scopes("full")) == len(eventbrite.CITIES) + 1
    assert not eventbrite.HACK_RE.search("Startup Pitch & Networking") and eventbrite.NOISE_RE.search("10 life hacks")


def test_allhackathons():
    rows = allhackathons.parse_list(read("allhackathons/list.html"))
    assert [r["slug"] for r in rows] == ["loopos-inc", "brewing-codes-4-0", "hack-the-farm", "hoya-hacks-2027"]
    assert rows[0]["start"] is None and rows[1]["format"] == "online"
    assert rows[2]["start"].year == 2099 and rows[2]["end"].day == 29
    assert rows[1]["themes"] == ["low/no-code", "machine learning", "web"]
    assert allhackathons._dates("Dec. 31, 2026")[0] == allhackathons._dates("Dec. 31, 2026")[1]
    assert allhackathons._date("Sept. 5, 2026").month == 9 and allhackathons._date("Date TBD") is None
    detail = allhackathons.parse_detail(read("allhackathons/detail.html"))
    assert detail["location"] == "Yaounde" and detail["description"].startswith("Quinze")
    assert "ai" in detail["themes"] and detail["website"] == "https://yaounde.impacthub.net/events/hackathon/"
    assert detail["organizer"] == "Impact Hub Yaounde"
    site = allhackathons.parse_detail(read("allhackathons/detail_site.html"))
    assert site["website"] == "https://hackathon.homingo.co.in/?ref=x"  # utm_* dropped, other params kept
    farm = allhackathons._event(rows[2], detail)
    hoya = allhackathons._event(rows[3], {"website": site["website"], "prize": "$0", "organizer": "Hoya Hacks"})
    check_fields([farm, hoya])
    assert farm.url == detail["website"] and farm.organizer == "Impact Hub Yaounde" and farm.format == "in-person" and farm.location == "Yaounde"
    assert hoya.url == site["website"] and hoya.prize is None and hoya.organizer == "Hoya Hacks"
    assert farm.kind == "hackathon" and farm.classified_by == "source" and farm.source_id == "hack-the-farm"
    big = allhackathons._event(rows[1], {"prize": "$5,000"})
    assert big.prize == "$5,000" and big.prize_usd == 5000 and big.location is None


def test_zindi():
    data = json.loads(read("zindi/competitions.json"))["data"]
    events = zindi.parse(data)
    check_fields(events)
    assert len(events) == 2  # third row is a closed, past competition
    first = events[0]
    assert first.url == "https://zindi.africa/competitions/" + data[0]["id"]
    assert first.prize == "$10 000 USD" and first.prize_usd == 10000 and first.organizer == "ITU"
    assert first.format == "online" and first.kind == "coding_competition" and first.classified_by == "source"
    assert first.participants == data[0]["participations_count"] and first.start.year == 2099
    assert events[1].prize == "R25 000 ZAR" and events[1].prize_usd is None  # only USD sets prize_usd
    assert zindi.parse([dict(data[2], open=False)]) == []


def test_devnovate():
    events = devnovate.parse(json.loads(read("devnovate/events.json")))
    check_fields(events)
    by = {e.source_id and e.url.rsplit("/", 1)[1]: e for e in events}
    # noor-hackathon ended in 2026 and codex-2.0 has junk dates ("34 days left") and CLOSED status.
    assert set(by) == {"whackiest", "prompt-war-x-syntax-squad", "bengaluru-builders-table"}
    w = by["whackiest"]
    assert (w.start.year, w.start.month, w.start.day) == (2099, 12, 1)  # DD-MM-YYYY
    assert w.format == "in-person" and w.location == "Ramaiah Institute of Technology"
    assert w.kind == "hackathon" and w.participants == 2414 and w.organizer == "CodeRIT"
    assert w.prize.startswith("₹1,50,000") and w.prize_usd is None and "Generative AI" in w.tags
    assert by["prompt-war-x-syntax-squad"].format == "online" and by["prompt-war-x-syntax-squad"].location is None
    meetup = by["bengaluru-builders-table"]
    assert meetup.kind == "unknown" and meetup.prize is None  # eventType "event": classify.py decides
    assert devnovate._day("34 days left") is None and devnovate._day("2026-11-21").month == 11


def test_hack2skill():
    data = json.loads(read("hack2skill/list.json"))
    details = json.loads(read("hack2skill/details.json"))
    events = hack2skill.parse(data, details)
    check_fields(events)
    by = {e.source_id: e for e in events}
    # aibuildercup2026 (registration closed 2026-10) and codeverse2025 are filtered out.
    assert set(by) == {"build2036", "pwvirtual1"}
    b = by["build2036"]
    assert b.url == "https://hack2skill.com/event/build2036" and b.format == "hybrid"
    assert b.kind == "hackathon" and b.start.year == 2099 and b.registration_deadline.year == 2099
    assert b.participants == 587 and "free" in b.tags and "flagship" in b.tags
    assert by["pwvirtual1"].kind == "unknown" and by["pwvirtual1"].format == "online"  # no details fetched


def test_globalgamejam():
    start, end = globalgamejam.jam_dates(read("globalgamejam/home.txt"))
    assert (start.day, end.day, end.month, end.year) == (25, 31, 1, 2027) and start.month == 1
    one, _ = globalgamejam.jam_dates("Jam Dates 28 February - 2 March 2027")
    assert (one.month, one.day) == (2, 28)
    assert globalgamejam.jam_dates("nothing here") == (None, None)
    events = globalgamejam.parse(read("globalgamejam/list.html"), 2027, start, end, "in-person")
    check_fields(events)
    assert len(events) == 3 and events[0].title == "GGJ27 - Gurgaon - UIDNCR GDGU"
    first = events[0]
    assert first.url == "https://globalgamejam.org/jam-sites/2027/ggj27-gurgaon-uidncr-gdgu"
    assert first.location == "Gurugram, Haryana, India" and first.country == "India"
    assert first.kind == "game_jam" and first.classified_by == "source" and first.start == start
    assert events[1].image is None  # default placeholder image dropped
    online = globalgamejam.parse(read("globalgamejam/list.html"), 2027, start, end, "online")
    assert all(e.location is None for e in online)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
