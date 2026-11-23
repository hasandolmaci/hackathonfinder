"""Plain-assert offline checks for C1. Run: python tests/test_new_sources_e.py."""
import copy
import json
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackfinder.collectors import aitinkerers, builderbase, colosseum, govtechnl, hackindia, raptors, superteam, twohero, whereuelevate

FIX = ROOT / "tests" / "fixtures"


def read(cid, name):
    return (FIX / cid / name).read_text(encoding="utf-8")


def data(cid, name):
    return json.loads(read(cid, name))


def fields(events):
    assert len({e.url for e in events}) == len(events)
    for e in events:
        assert e.url.startswith("https://") and e.title and e.source
        for stamp in (e.start, e.end, e.registration_deadline):
            assert stamp is None or stamp.utcoffset() == timedelta(0)
        assert len(e.signals.get("text", "")) <= 3000
        if e.format == "online":
            assert e.location is None


def test_builderbase():
    rows = data("builderbase", "listing.json")["data"]["super_events"]
    events = [builderbase._event(r) for r in rows]
    fields(events)
    assert all(e.kind == "unknown" and e.confidence == 0 for e in events)
    assert all("registrations" in e.signals for e in events)
    assert events[0].organizer
    r = {**rows[0], "end_at": "2000-01-01T00:00:00Z"}
    assert builderbase._event(r) is None
    r = {**rows[0], "location": {"lat": 52.1, "lng": 4.3, "country": "NL", "city": "Delft"}, "format": "onsite"}
    e = builderbase._event(r)
    assert e.country == "NL" and e.signals["lat"] == 52.1


class Client:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_builderbase_cursor_and_stall():
    rows = data("builderbase", "listing.json")["data"]["super_events"]
    calls = []
    def get(c, url, **kwargs):
        if "/browse" not in url:
            row = next(r for r in rows if url.endswith(r["slug"]))
            return {"data": {"super_event": {**row, "description": "A public hackathon."}}}
        cursor = kwargs["params"].get("cursor")
        calls.append(cursor)
        # Overlapping pages must not truncate after the first overlap; a fully repeated page stops.
        page = rows[:1] if cursor is None else rows
        return {"data": {"super_events": page, "next_cursor": "second" if cursor is None else "third" if cursor == "second" else "fourth"}}
    with patch.object(builderbase, "client", return_value=Client()), patch.object(builderbase, "robots"), patch.object(builderbase, "polite_json", side_effect=get):
        events = builderbase.collect()
    assert len(events) == 2 and calls == [None, "second", "third"]
    assert events[0].signals["text"] == "A public hackathon."


def test_twohero():
    d = data("twohero", "bundle.json")
    events = twohero.parse(d)
    fields(events)
    assert len(events) == 2  # Published program state, not a future draft.
    assert all(e.kind == "hackathon" and e.confidence == 0.9 for e in events)
    assert any(e.format == "online" for e in events)
    assert all("/hackathons/" in e.url for e in events)
    d = copy.deepcopy(d)
    for r in d["programs"]:
        r["ends"] = "2000-01-01"
    assert twohero.parse(d) == []


def test_hackindia():
    html = read("hackindia", "listing.html")
    events = hackindia.parse(html)
    fields(events)
    assert len(events) == 2
    assert events[0].signals["prize_amount"] == 100000 and events[0].signals["prize_currency"] == "INR"
    assert events[0].signals["registrations"] == 26 and events[0].country == "India"
    assert events[1].format == "online" and events[1].country is None
    assert events[0].url.endswith("/2099/mailam-builds27")
    assert hackindia.parse(html.replace("2099-", "2000-")) == []
    assert hackindia._event({"title": "Cancelled", "start_date": "2099-01-01", "is_cancelled": 1}) is None


def test_whereuelevate():
    rows = data("whereuelevate", "listing.json")["result"]["content"]
    events = [whereuelevate._event(r) for r in rows]
    fields(events)
    assert len(events) == 3 and events[0].signals["registrations"] == 0
    assert events[2].signals["prize_currency"] == "INR" and events[2].signals["prize_amount"] == 40000
    assert all(e.kind == "unknown" for e in events)
    r = copy.deepcopy(rows[0])
    r["drillRegistration"]["externalRegistrationLink"] = "https://original.example/register"
    assert whereuelevate._event(r).url == "https://original.example/register"
    assert whereuelevate._event({**r, "status": "COMPLETED"}) is None
    assert whereuelevate._event({**r, "endTs": "2000-01-01"}) is None


def test_whereuelevate_pagination():
    rows = data("whereuelevate", "listing.json")["result"]["content"]
    offsets = []
    def get(c, url, **kwargs):
        page = kwargs["params"]["offset"]
        offsets.append(page)
        return {"result": {"content": rows[page:page+1], "last": page == 2, "totalPages": 3}}
    with patch.object(whereuelevate, "client", return_value=Client()), patch.object(whereuelevate, "robots"), patch.object(whereuelevate, "polite_json", side_effect=get):
        events = whereuelevate.collect()
    assert offsets == [0, 1, 2] and len(events) == 3


def test_aitinkerers():
    html = read("aitinkerers", "listing.html")
    events = aitinkerers.parse(html)
    fields(events)
    assert len(events) == 2 and len(aitinkerers.links(html)) == 2
    assert all(e.kind == "unknown" and e.classified_by == "none" for e in events)
    assert events[0].start.hour == 17  # 18:00 CET, preserved in UTC.
    assert aitinkerers.parse(html.replace("2098-", "2000-")) == []
    assert aitinkerers.parse(html.replace("EventScheduled", "EventCancelled")) == []


def test_raptors():
    urls = raptors.listing(read("raptors", "listing.html"))
    assert urls == ["https://agentwarehack.com/", "https://codeolympics.com/winter-2098"]
    html = read("raptors", "event.html")
    events = raptors.parse(html, urls[0])
    fields(events)
    assert len(events) == 1 and events[0].kind == "hackathon"
    assert events[0].url == "https://agentwarehack.com/"
    assert events[0].signals["prize_amount"] == 1800 and events[0].organizer == "Hackathon Raptors"
    assert events[0].signals["themes"] and events[0].format == "online"
    assert raptors.parse(html.replace("2098-", "2000-"), urls[0]) == []


def test_colosseum():
    state = colosseum._state(data("colosseum", "state.json"))
    url = "https://colosseum.com/eternal"
    pages = {url: read("colosseum", "eternal.html")}
    events = colosseum.parse(state, pages)
    fields(events)
    assert len(events) == 1 and events[0].title == "Colosseum Eternal"  # Judging is not open.
    assert events[0].start is None and events[0].end.year == 2099
    assert events[0].signals["registrations"] == 184
    assert events[0].signals["prize_amount"] == 25000 and events[0].signals["prize_currency"] == "USDC"
    state["programs"]["eternal"]["endDate"] = "2000-01-01"
    assert colosseum.parse(state, pages) == []


def test_superteam():
    urls = superteam.links(read("superteam", "listing.html"))
    assert urls == ["https://superteam.fun/earn/hackathon/crypto-worlds-fair"]
    html = read("superteam", "event.html")
    events = superteam.parse(html, urls[0])
    fields(events)
    assert len(events) == 1 and events[0].kind == "hackathon" and events[0].organizer
    assert superteam.parse(html.replace("2098-", "2000-"), urls[0]) == []


def test_govtechnl():
    html = read("govtechnl", "calendar.html")
    events = govtechnl.parse(html)
    fields(events)
    assert len(events) == 1 and events[0].title.startswith("OneGov")
    assert events[0].url.startswith("https://www.eventbrite.nl/")
    assert events[0].country == "NL" and events[0].signals["lat"] == 52.070071
    assert events[0].kind == "unknown"
    assert govtechnl.parse(html.replace("2098-", "2000-")) == []


def test_schema_drift_and_fixture_sizes():
    for fn, value in [(hackindia.parse, "<html></html>"), (govtechnl.parse, "<html></html>"),
                      (raptors.listing, "<html></html>"), (twohero.parse, {}), (colosseum._state, {})]:
        try:
            fn(value)
        except RuntimeError:
            pass
        else:
            assert False, f"{fn} silently accepted schema drift"
    for cid in ("builderbase", "twohero", "hackindia", "whereuelevate", "aitinkerers", "raptors", "colosseum", "superteam", "govtechnl"):
        assert all(p.stat().st_size < 100000 for p in (FIX / cid).iterdir())


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn)]
    for name, fn in tests:
        fn()
        print(name + ": PASS")
    print(f"{len(tests)} offline tests passed")
