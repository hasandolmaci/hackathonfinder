"""Offline assertions; compact API-shaped fixtures stay in this owned file.

Run: python -m pytest tests/test_luma_complete.py
No live requests and no writes to the real calendar watchlist.
"""
import copy
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx

from hackfinder.collectors import luma as l


def entry(api_id="evt-one", title="Community Hackathon"):
    return {"event": {"api_id": api_id, "name": title, "url": "sample",
        "start_at": "2098-11-25T10:00:00+01:00", "end_at": "2098-11-26T16:00:00Z",
        "location_type": "offline", "calendar_api_id": "cal-one", "user_api_id": "usr-one",
        "geo_address_info": {"city": "Berlin", "country": "Germany", "full_address": "Berlin venue"},
        "coordinate": {"latitude": 52.52, "longitude": 13.405}},
        "calendar": {"api_id": "cal-one", "name": "Builders", "slug": "builders"},
        "hosts": [{"api_id": "usr-one", "name": "Host"}], "guest_count": 42,
        "ticket_info": {"is_free": False, "price": {"cents": 1500, "currency": "eur"}},
        "description_mirror": {"type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Cash prize pool: EUR 1000."}]}]},
        "categories": [{"name": "AI"}], "sponsors": [{"name": "Sponsor"}]}


def isolated():
    return patch.multiple(l, _calendars={}, _hosts={}, _entries={})


def test_normalization():
    e = l._event(entry())
    assert e.url == "https://luma.com/sample" and e.kind == "unknown" and e.confidence == 0
    assert e.start.hour == 9 and e.start.utcoffset().total_seconds() == 0
    assert (e.format, e.country, e.organizer, e.participants) == ("in-person", "Germany", "Host", 42)
    assert e.signals["registrations"] == e.signals["guests"] == 42
    assert e.signals["lat"] == 52.52 and e.signals["host_ids"] == ["usr-one"]
    assert e.signals["entry_fee"] == "15.00 EUR" and e.signals["paid_entry"] is True
    assert e.signals["themes"] == ["AI"] and e.signals["sponsors"] == ["Sponsor"]
    assert e.prize == "1000 EUR" and e.signals["prize_amount"] == 1000


def test_filter_and_unique_evidence():
    with isolated():
        a = entry()
        assert len(l.relevant_events([a, a])) == 1
        assert l._calendars["cal-one"]["hits"] == 1 and "usr-one" in l._hosts
        b = entry("evt-two", "Build Night")
        assert len(l.relevant_events([b])) == 1 and l._calendars["cal-one"]["hits"] == 2
        c = entry(title="Picnic")
        c.pop("description_mirror")
        assert not l.relevant_events([c])
        c["description_mirror"] = {"type": "text", "text": "Join our game jam"}
        assert l.relevant_events([c])
        c["event"]["end_at"] = "2000-01-01T00:00:00Z"
        assert not l.relevant_events([c])
        c = entry()
        c["event"]["cancelled_at"] = "2098-01-01T00:00:00Z"
        assert not l.relevant_events([c])


def test_external_url_and_hidden_counts():
    a = entry()
    a["event"].update(url="https://organizer.example/register", hide_rsvp=True, location_type="online")
    e = l._event(a)
    assert e.url == "https://organizer.example/register" and e.location is None and e.country is None
    assert "guests" not in e.signals and "registrations" not in e.signals


def test_hybrid_and_text_limit():
    a = entry()
    a["ticket_types"] = [{"name": "Online"}, {"name": "Venue"}]
    a["event"]["description"] = "hack " * 1000
    e = l._event(a)
    assert e.format == "hybrid" and len(e.signals["text"]) <= 3000
    a["ticket_types"] = [{"name": "Online"}]
    assert l._event(a).format == "online"


def test_non_cash_not_entry_price():
    a = entry()
    a["event"]["description"] = "Tickets cost EUR 15. Prizes: EUR 3000 in credits."
    assert l._event(a).prize is None


def test_pages_use_real_cursor():
    replies = [{"entries": [entry()], "has_more": True, "next_cursor": "cursor-a"},
               {"entries": [entry("evt-two")], "has_more": False, "next_cursor": "terminal"}]
    params = {"discover_place_api_id": "place", "pagination_limit": 50}
    with patch.object(l, "_get", side_effect=replies) as get:
        assert len(list(l._pages(None, params))) == 2
        assert get.call_args_list[1].args[1]["pagination_cursor"] == "cursor-a"
        assert "pagination_cursor" not in params


def test_pages_stop_repeated_ids_and_cursor():
    a = {"entries": [entry()], "has_more": True, "next_cursor": "same"}
    with patch.object(l, "_get", side_effect=[a, a]) as get:
        assert len(list(l._pages(None, {}))) == 1 and get.call_count == 2
    b = {"entries": [entry("evt-two")], "has_more": True, "next_cursor": "same"}
    with patch.object(l, "_get", side_effect=[a, b]) as get:
        assert len(list(l._pages(None, {}))) == 2 and get.call_count == 2


def test_pages_missing_cursor_empty_and_schema():
    for data in [{"entries": []}, {"entries": [entry()], "has_more": True},
                 {"entries": [entry()], "has_more": False, "next_cursor": "ignored"}]:
        with patch.object(l, "_get", return_value=data) as get:
            list(l._pages(None, {}))
            assert get.call_count == 1
    with patch.object(l, "_get", return_value={"changed": []}):
        try:
            list(l._pages(None, {}))
            assert False, "schema changes must fail"
        except RuntimeError:
            pass


def test_safety_limit():
    def page(c, params):
        n = int(params.get("pagination_cursor", 0)) + 1
        return {"entries": [entry(f"evt-{n}")], "has_more": True, "next_cursor": str(n)}
    with patch.object(l, "_get", side_effect=page), patch.object(l, "warn_limit") as warn:
        assert len(list(l._pages(None, {}))) == 100
        assert warn.call_count == 1


def test_learning_opt_in_and_merge():
    with isolated(), tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "calendars.json"
        original = {"comment": "preserve", "calendars": [{"api_id": "cal-existing", "name": "Keep"}]}
        path.write_text(json.dumps(original), encoding="utf-8")
        with patch.object(l, "CALENDARS_FILE", path), patch.dict(os.environ, {"HF_LUMA_LEARN": "0"}):
            l.relevant_events([entry(), entry()])
            l.learn_calendars()
            assert json.loads(path.read_text()) == original
            with patch.dict(os.environ, {"HF_LUMA_LEARN": "1"}):
                l.learn_calendars()
                assert len(json.loads(path.read_text())["calendars"]) == 1
                l.relevant_events([entry("evt-two")])
                l.learn_calendars()
                data = json.loads(path.read_text())
                assert data["comment"] == "preserve" and len(data["calendars"]) == 2
                assert data["calendars"][1]["last_seen"] and data["calendars"][1]["slug"] == "builders"
                assert len(list(Path(directory).iterdir())) == 1


def test_host_expansion_and_new_calendar():
    with isolated(), patch.dict(os.environ, {"HF_LUMA_LEARN": "0"}):
        l.relevant_events([entry()])
        extra = entry("evt-extra")
        extra["calendar"] = {"api_id": "cal-new", "name": "New"}
        extra["hosts"] = [{"api_id": "usr-new", "name": "New host"}]
        with patch.object(l, "_pages", return_value=iter([[extra]])) as pages, \
             patch.object(l, "_collect_calendars", return_value=[]) as calendars:
            assert len(l._collect_hosts()) == 1
            assert pages.call_count == 1  # one hop; newly encountered hosts wait for another run
            assert pages.call_args.args[1]["_path"] == "/user/profile/events-hosting"
            assert calendars.call_args.args[0] == [("cal-new", "New")]


def test_detail_merge_preserves_listing_fields():
    with isolated(), patch.dict(os.environ, {"HF_LUMA_LEARN": "0"}):
        l.relevant_events([entry()])
        detail = {"event": {"description": "A hackathon with a prize pool of EUR 2000."}}
        with patch.object(l, "_get", return_value=detail):
            e = l._collect_details()[0]
        assert e.start and e.signals["calendar_id"] == "cal-one" and e.prize == "2000 EUR"


def test_calendar_deleted_does_not_drop_next():
    error = httpx.HTTPStatusError("deleted", request=httpx.Request("GET", "https://api.lu.ma/calendar/get-items"),
                                 response=httpx.Response(404))
    with isolated(), patch.dict(os.environ, {"HF_LUMA_LEARN": "0"}), \
         patch.object(l, "_pages", side_effect=[error, iter([[entry()]])]):
        assert len(l._collect_calendars([("deleted", "Gone"), ("cal-one", "Builders")])) == 1


def test_scopes_and_state_reset():
    with isolated(), patch.object(l, "_places", {"berlin": "p"}), patch.object(l, "_categories", {"ai": "a"}):
        l._hosts["old"] = {}
        quick = l.scopes("quick")
        assert len(quick) == 10 and not l._hosts and "details" not in quick
        full = l.scopes("full")
        assert "feed:berlin" in full and "category:ai" in full
        assert full[-3:] == ["calendars", "hosts", "details"] and "sitemap" not in full
        assert l.RANKED_SEARCH is True


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
    print(f"{len(tests)} Luma offline tests passed")
