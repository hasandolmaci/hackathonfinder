"""Offline scoring evidence and itch.io rate-limit regressions."""
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hackfinder.collectors import (allhackathons, commudle, devfolio, devnovate, dorahacks,
    encodeclub, eventbrite, hack2skill, hackjunction, hackquest, itchio, kaggle, wemakedevs, zindi)
from hackfinder.collectors._signals_util import count, reward, source_signals
from hackfinder.models import Event

FIX = Path(__file__).parent / "fixtures"
FUTURE = "2099-12-01T00:00:00Z"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@contextmanager
def api(module, payload):
    def request(request):
        return httpx.Response(200, json=payload)
    client = httpx.Client(transport=httpx.MockTransport(request))
    try:
        with patch.object(module, "client", return_value=client), patch.object(module, "check_robots"):
            yield
    finally:
        client.close()


def test_devpost():
    from hackfinder.collectors import devpost
    row = dict(id=1, title="Future", url="https://example.com", open_state="open",
        submission_period_dates="Dec 01 - 02, 2099", registrations_count=0, featured=False,
        invite_only=True, managed_by_devpost_badge=True, prizes_counts={"other": 2},
        prize_amount='$<span data-currency-value>100,000</span>', themes=[{"name": "AI"}])
    with api(devpost, {"hackathons": [row], "meta": {"total_count": 1}}):
        e = devpost.collect()[0]
    assert e.participants == 0
    assert e.signals == dict(registrations=0, featured=False, official=True, invite_only=True,
        themes=["AI"], prize_noncash=True, prize_amount=100000.0, prize_currency="USD")


def test_devfolio():
    row = dict(uuid="1", name="Future", slug="future", starts_at=FUTURE, ends_at=FUTURE,
        desc="<p>" + "Full description " * 300 + "</p>", tagline="Short", participants_count=50,
        devfolio_official=True, verified=True, featured=False, projects_submitted=0,
        hackathon_setting={"women_only": True}, judges=[{"name": "Judge"}],
        sponsor_tiers=[{"sponsors": [{"name": "Sponsor"}, {"name": "Sponsor"}]}],
        prizes=[{"name": "Credits", "desc": "$500 in credits"}])
    e = devfolio._event(row)
    assert e.participants == 50 and e.signals["registrations"] == 50
    assert e.signals["sponsors"] == ["Sponsor"] and e.signals["judges"] == 1
    assert e.signals["entries"] == 0 and e.signals["women_only"] is True
    assert e.signals["official"] is True and e.signals["featured"] is False
    assert e.signals["prize_noncash"] is True and "prize_amount" not in e.signals
    assert len(e.signals["text"]) == 3000 and e.signals["text"].startswith("Full description")
    row["prizes"] = [{"uuid": "pool", "desc": "Cash prize of ₹10,000 INR"},
        {"parent_prize_uuid": "pool", "desc": "Cash prize of ₹7,000 INR awarded to the winner."},
        {"parent_prize_uuid": "pool", "desc": "Cash prize of ₹3,000 INR for second place."}]
    assert devfolio._event(row).signals["prize_amount"] == 10000


def test_unstop():
    from hackfinder.collectors import unstop
    row = dict(id=1, title="Future", public_url="future", start_date=FUTURE, end_date=FUTURE,
        registerCount=12, isPaid=False, actively_hiring=True, details="<p>Rules</p>",
        regnRequirements={"eligibility": json.dumps({"sector": ["students"]})},
        prizes=[{"cash": 500, "currencyCode": "INR", "prize_type": "cash"},
                {"cash": 100, "currencyCode": "INR", "prize_type": "cash"},
                {"others": "Swag", "prize_type": "in_kind"}])
    e = unstop._event(row)
    assert e.signals == dict(text="Rules", registrations=12, paid_entry=False, hiring=True,
        students_only=True, prize_noncash=True, prize_amount=600.0, prize_currency="INR")
    row["prizes"].append({"cash": 100, "currencyCode": "USD", "prize_type": "cash"})
    assert "prize_amount" not in unstop._event(row).signals
    row["regnRequirements"]["eligibility"] = '{"sector":["students","professionals"]}'
    assert unstop._event(row).signals["students_only"] is False


def test_ctftime():
    from hackfinder.collectors import ctftime
    row = dict(id=1, title="CTF", start=FUTURE, finish=FUTURE, weight=0.0,
        ctf_id=42, participants=29, restrictions="Open", description="<p>Rules</p>")
    with api(ctftime, [row]):
        e = ctftime.collect()[0]
    assert e.participants == 29
    assert e.signals == dict(text="Rules", ctf_weight=0.0, ctf_id=42, teams=29,
        series_id="42", invite_only=False)


def test_mlh():
    from hackfinder.collectors import mlh
    row = dict(id="1", name="Future", url="https://example.com", startsAt=FUTURE, endsAt=FUTURE)
    with api(mlh, {"props": {"upcomingEvents": [row]}}):
        assert mlh.collect()[0].signals == {"mlh_member": True}


def test_taikai():
    from hackfinder.collectors import taikai
    row = dict(id="1", name="Future", slug="future", organization={"name": "Host", "slug": "host"},
        steps=[{"name": "Hackathon start", "startDate": FUTURE}], prize=5000,
        prizeCurrency={"name": "EUR"}, participantsCount=20, shortDescription="Rules")
    replies = iter([{"data": {"challenges": [row]}}, {"data": {"challenges": []}}])
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=next(replies))))
    try:
        with patch.object(taikai, "client", return_value=c), patch.object(taikai, "check_robots"):
            e = taikai.collect()[0]
    finally:
        c.close()
    assert e.signals == dict(text="Rules", registrations=20, prize_amount=5000.0, prize_currency="EUR")
    assert e.prize_usd is None


def test_kaggle():
    e = kaggle._event(dict(title="Future", ref="future", deadline=FUTURE, teamCount=42,
        category="Featured", reward="$50,000", description="Full rules"))
    assert e.participants is None
    assert e.signals == dict(text="Full rules", teams=42, kaggle_category="Featured",
        prize_amount=50000.0, prize_currency="USD")


def test_new_api_sources():
    e = devnovate.parse(load("devnovate/events.json"))[0]
    assert e.signals["registrations"] == 2414 and e.signals["paid_entry"] is False
    assert e.signals["prize_currency"] == "INR" and e.signals["prize_amount"] == 150000
    assert e.signals["prize_noncash"] is True and e.signals["themes"]
    e = hack2skill.parse(load("hack2skill/list.json"), load("hack2skill/details.json"))[0]
    assert e.signals == dict(registrations=587, paid_entry=False, region_locked=False)
    events = zindi.parse(load("zindi/competitions.json")["data"])
    assert events[0].signals["registrations"] == 1620 and events[0].signals["prize_currency"] == "USD"
    assert events[1].signals["prize_currency"] == "ZAR" and events[1].signals["prize_amount"] == 25000
    e = hackquest._event(load("hackquest/list.json")["data"]["listHackathons"]["data"][0])
    assert e.signals["registrations"] == 36 and e.signals["entries"] == 1
    assert e.signals["judges"] == 3 and e.signals["prize_currency"] == "USDC"
    assert e.signals["text"].startswith("Arbitrum Open House")
    e = commudle._event(load("commudle/future.json")["data"]["page"][0]["data"])
    assert e.participants == 5000 and e.signals["capacity"] == 5000
    assert "registrations" not in e.signals and e.signals["prize_currency"] == "INR"
    e = hackjunction._event(load("hackjunction/trpc.json")[0]["result"]["data"]["json"][0])
    assert e.signals["featured"] is False and e.signals["text"]


def test_new_browser_sources():
    data = load("dorahacks/hub.json")
    e = dorahacks._event(data["rows"][0], data["detail"])
    assert e.signals["registrations"] == data["rows"][0]["hackers_count"]
    assert e.signals["entries"] == 0 and e.signals["tracks"] == 2
    assert e.signals["prize_currency"] == "USD" and e.signals["text"].startswith("# Overview")
    e = encodeclub._event(load("encodeclub/programmes.json")[0])
    assert e.signals["registrations"] == 1222 and e.signals["featured"] is True
    assert e.signals["text"].startswith("Calling all")
    cards = wemakedevs._cards((FIX / "wemakedevs/listing.html").read_text(encoding="utf-8"))
    events = [e for c in cards if (e := wemakedevs._event(c))]
    assert events and all(e.signals.get("text") for e in events)
    e = wemakedevs._event({**cards[0], "seriesSlug": "annual-build", "endDate": FUTURE})
    assert e.signals["series_id"] == "annual-build"


def test_aggregator_text():
    html = (FIX / "allhackathons/detail.html").read_text(encoding="utf-8")
    row = allhackathons.parse_list((FIX / "allhackathons/list.html").read_text(encoding="utf-8"))[1]
    detail = allhackathons.parse_detail(html)
    e = allhackathons._event(row, detail)
    assert e.signals["text"] == detail["text"] and e.signals["themes"] == detail["themes"]
    events, _, _ = eventbrite.parse((FIX / "eventbrite/search.html").read_text(encoding="utf-8"))
    assert events[0].signals["text"]


def test_hackclub_and_hackerearth():
    from hackfinder.collectors import hackclub, hackerearth
    row = dict(id="1", name="Future", start=FUTURE, end=FUTURE,
        mlhAssociated=False, hack_club_event=True)
    with api(hackclub, {"pageProps": {"events": [row]}}):
        assert hackclub.collect()[0].signals == {"mlh_member": False, "official": True}
    row = dict(title="Future", url="https://www.hackerearth.com/challenges/hackathon/future/",
        status="UPCOMING", start_utc_tz=FUTURE, end_utc_tz=FUTURE, college=False,
        description="Full rules", is_hackerearth=True)
    with api(hackerearth, {"response": [row]}):
        assert hackerearth.collect()[0].signals == {"students_only": False, "text": "Full rules"}


def test_globalgamejam():
    from hackfinder.collectors import globalgamejam
    events = globalgamejam.parse((FIX / "globalgamejam/list.html").read_text(encoding="utf-8"), 2099)
    assert events and all(e.signals == {"hosts": ["Global Game Jam"], "series_id": "globalgamejam"} for e in events)


def test_hack2skill_full_text():
    data = load("hack2skill/list.json")
    details = load("hack2skill/details.json")
    details["build2036"]["sections"] = [{"type": "ABOUT", "category": [{"data": [
        {"description": "<style>.junk {color:red}</style><p>Mentors and rules</p>"},
        {"description": "Hidden", "isHidden": True}]}]}]
    assert hack2skill.parse(data, details)[0].signals["text"] == "Mentors and rules"


def test_saved_browser_pages():
    from hackfinder.collectors import ethglobal, hackathoncom, lablab
    pages = Path(os.environ.get("HF_PARSER_PAGES", r"C:\Users\hasan\AppData\Local\Temp\claude\98baf456b77d57f6\ddcb85d0-6bf3-4dc9-b896-1d6cb647e0cd\scratchpad\pages"))
    if not (pages / "kaggle_active1.html").exists():
        pytest.skip("browser snapshots are not installed")
    e = kaggle.parse((pages / "kaggle_active1.html").read_text(encoding="utf-8"), kaggle.ACTIVE)[0]
    assert e.signals["teams"] == 2375 and e.signals["kaggle_category"] == "Featured"
    assert e.signals["prize_amount"] == 50000 and e.participants is None
    events = ethglobal.parse((pages / "ethglobal.html").read_text(encoding="utf-8"), ethglobal.SOURCE["url"])
    assert events and all(e.signals["hosts"] == ["ETHGlobal"] for e in events)
    events = hackathoncom.parse((pages / "hackathoncom.html").read_text(encoding="utf-8"), hackathoncom.SOURCE["url"])
    assert any(e.signals.get("prize_amount") == 15000 for e in events)
    raw = {"@type": "Event", "name": "Future", "url": "/future", "endDate": FUTURE,
           "description": "<p>" + "Full rules " * 300 + "</p>"}
    html = '<script type="application/ld+json">' + json.dumps(raw) + '</script>'
    e = lablab.parse(html, lablab.LISTING)[0]
    assert len(e.signals["text"]) == 3000


def test_itchio_calendar():
    e = itchio._calendar_event(dict(id=1, title="Jam", url="/jam/test", start_date=FUTURE,
        end_date=FUTURE, joined=0, featured=1, short_text="Rules"))
    assert e.signals == dict(joined=0, featured=True, text="Rules")
    # Preserve the old public participants behavior, independently of the raw zero signal.
    assert e.participants is None


def test_itchio_cards():
    raw = dict(title="Jam", url="https://itch.io/jam/test", date=FUTURE, hosts=["Host", "Co-host"],
        text="Submission closes in 10 days. 1,234 joined 8 submissions")
    page = SimpleNamespace(evaluate=lambda *a: None, wait_for_timeout=lambda *a: None,
        locator=lambda *a: SimpleNamespace(evaluate_all=lambda *a: [raw]))
    events = {}
    with patch.object(itchio, "_navigate"), patch.object(itchio, "check_block"), \
         patch.object(itchio, "embedded", return_value=[]), patch.object(itchio, "script_objects", return_value=[]):
        assert itchio._scan(page, "https://itch.io/jams", events) == {raw["url"]}
    e = events[raw["url"]]
    assert e.signals == dict(joined=1234, entries=8, hosts=["Host", "Co-host"], text=raw["text"])
    assert e.participants == 1234 and e.organizer == "Host, Co-host"


class Page:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.waits, self.loads = [], 0

    def wait_for_timeout(self, value):
        self.waits.append(value)

    def goto(self, *args, **kwargs):
        self.loads += 1
        return next(self.responses)

    def wait_for_selector(self, *args, **kwargs):
        pass


@pytest.mark.parametrize("retry_after", ["45", format_datetime(datetime.now(timezone.utc) + timedelta(seconds=45))])
def test_itchio_retry_after(retry_after):
    p = Page([SimpleNamespace(status=429, headers={"retry-after": retry_after}), SimpleNamespace(status=200)])
    with patch.object(itchio, "check_block"):
        itchio._navigate(p, "https://itch.io/jams")
    assert p.loads == 2 and p.waits[1] >= 43000
    assert 2000 <= p.waits[0] <= 3000 and 2000 <= p.waits[2] <= 3000


def test_itchio_exhausted_retries():
    p = Page([SimpleNamespace(status=429, headers={}) for _ in range(3)])
    with pytest.raises(RuntimeError, match="429"):
        itchio._navigate(p, "https://itch.io/jams")
    assert p.loads == 3
    assert p.waits[1] >= 5000 and p.waits[3] >= 10000


@pytest.mark.parametrize("collected", [True, False])
def test_itchio_partial(collected):
    @contextmanager
    def browser():
        yield object()

    def scan(page, url, events):
        if collected and not events:
            e = Event(source="itchio", url="https://itch.io/jam/test", title="Jam")
            events[e.url] = e
            return {e.url}
        raise RuntimeError("blocked: HTTP 429")

    with patch.object(itchio, "cdp_page", browser), patch.object(itchio, "_scan", scan):
        if collected:
            assert len(itchio._collect()) == 1
        else:
            with pytest.raises(RuntimeError, match="429"):
                itchio._collect()


def test_missing_and_invalid_evidence():
    assert source_signals("devfolio", {}) == {}
    assert source_signals("ctftime", {}) == {}
    assert count("nan") is None and count(-1) is None and count(True) is None
    assert count("1,234") == 1234
    assert reward("TBA") == {} and reward("$10k") == {} and reward("$10 USD + 50 EUR") == {}
    assert reward("$500 in credits") == {}
    assert reward("R25 000 ZAR") == {"prize_amount": 25000.0, "prize_currency": "ZAR"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
