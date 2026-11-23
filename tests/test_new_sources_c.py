"""Plain-assert offline tests for group A aggregators. Run: python tests/test_new_sources_c.py"""
import importlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackfinder.collectors import _country_sites as country, eventornado as tornado, hackathonparty as party, openhackathons as opened

FIX = ROOT / "tests" / "fixtures"


def fixture(cid, name):
    return (FIX / cid / name).read_text(encoding="utf-8")


def test_country_discovery_and_original_url():
    mod = importlib.import_module("hackfinder.collectors.germanhackathons")
    urls = mod.event_urls(fixture("germanhackathons", "rss.xml"), fixture("germanhackathons", "sitemap.xml"))
    assert urls == ["https://germanhackathons.com/events/aeco-hackathon-bau-2027"]
    html = fixture("germanhackathons", "event.html")
    node = country.parse_event(html)
    event = country.to_event(node, urls[0], "germanhackathons", "Germany", html)
    assert event.url == "https://luma.com/gpm4s6w7"
    assert event.start.year == 2099 and event.start.hour == 10 and event.start.utcoffset().total_seconds() == 0
    assert event.country == "Germany" and event.location == "München, Germany"
    assert event.kind == "hackathon" and event.confidence == .9 and event.classified_by == "source"
    assert event.signals["paid_entry"] is False and event.prize is None
    assert event.signals["lat"] == 48.1494654 and event.signals["lon"] == 11.568812
    assert event.signals["themes"] == ["builtenvironment"]
    assert event.signals["text"] == "Researchers and students build together."
    assert event.organizer == "TUM Venture Labs Built Environment"


def test_country_filters_and_evidence():
    node = country.parse_event(fixture("germanhackathons", "event.html"))
    page = "https://germanhackathons.com/events/test"
    assert country.to_event({**node, "startDate": "2020-01-01", "endDate": "2020-01-02"}, page) is None
    assert country.to_event({**node, "eventStatus": "https://schema.org/EventCancelled"}, page) is None
    assert country.to_event({**node, "startDate": "bad", "endDate": None}, page) is None
    node.update(offers={"url": "https://event.example/register?id=7&utm_source=directory", "price": "10", "priceCurrency": "EUR"},
                eventAttendanceMode="https://schema.org/MixedEventAttendanceMode", attendeeCount=120,
                sponsor=[{"name": "Example Sponsor"}])
    html = '<main><section class="info-strip"><span class="chip-val gold">$5,000</span></section><p class="body-p">' + "x" * 3500 + '</p></main>'
    event = country.to_event(node, page, "germanhackathons", "Germany", html)
    assert event.url == "https://event.example/register?id=7" and event.format == "hybrid"
    assert event.participants == event.signals["registrations"] == 120
    assert event.prize_usd == event.signals["prize_amount"] == 5000
    assert event.signals["prize_currency"] == "USD" and event.signals["sponsors"] == ["Example Sponsor"]
    assert len(event.signals["text"]) == 3000 and event.signals["paid_entry"] is True
    node["offers"] = [{"url": "/go/test"}]
    assert country.to_event(node, page).url == page
    node["name"] = "Winter Game Jam"
    assert country.to_event(node, page).kind == "game_jam"


def test_all_country_wrappers():
    ids = "netherlandshackathons germanhackathons ukhackathons francehackathons spainhackathons japanhackathons turkeyhackathons hackathonsaustralia canadahackathons ushackathons hackathonsingapore mexicohackathons swedenhackathons italyhackathons vietnamhackathons hackathonhongkong argentinahackathons colombiahackathons pakistanhackathons austriahackathons indonesiahackathons indiahackathons koreahackathons taiwanhackathons thailandhackathons nzhackathons".split()
    node = country.parse_event(fixture("germanhackathons", "event.html"))
    for cid in ids:
        mod = importlib.import_module("hackfinder.collectors." + cid)
        page = mod.BASE + "/events/test"
        assert mod.SOURCE["id"] == cid and mod.SOURCE["method"] == "api"
        assert mod.event_urls("<loc>" + page + "</loc>") == [page]
        assert mod.to_event(node, page).source == cid


def test_country_collect_exhausts_sitemap_without_event_cap():
    node = country.parse_event(fixture("germanhackathons", "event.html"))
    html = '<script type="application/ld+json">' + json.dumps(node) + '</script>'
    base = "https://germanhackathons.com"
    sitemap = "<urlset>" + "".join(f"<loc>{base}/events/{n}</loc>" for n in range(105)) + "</urlset>"
    class Response:
        status_code = 200
        def __init__(self, text):
            self.text = text
        def raise_for_status(self):
            pass
    class Client:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url, **kwargs):
            return Response("<rss/>" if url.endswith("rss.xml") else sitemap if url.endswith("sitemap.xml") else html)
    with patch.object(country, "client", Client), patch.object(country, "check_robots", return_value=0), patch.object(country.time, "sleep"):
        events = country.collect_site({"id": "germanhackathons", "url": base}, "Germany")
    assert len(events) == 105 and len({e.source_id for e in events}) == 105


def test_eventornado_vue_json():
    listing = json.loads(fixture("eventornado", "list.json"))
    rows = tornado.parse_list(listing["events"])
    assert len(rows) == 5 and rows[0]["format"] == "hybrid"
    row = next(r for r in rows if "underground-innovation" in r["url"])
    data = tornado.parse_detail(fixture("eventornado", "detail.html"))
    event = tornado.to_event(row, data)
    assert event.start.year == 2098 and event.organizer == "EIS" and event.format == "online"
    assert event.url == row["url"] and event.kind == "hackathon"
    assert event.signals["themes"] and "ZeroTerrain" in event.signals["sponsors"]
    assert len(event.signals["text"]) <= 3000 and event.participants is None
    assert tornado.to_event(row, {**data, "end_date": "2020-01-01"}) is None
    assert tornado.to_event(row, {**data, "status": 2}) is None
    data["description"] = '<a href="https://register.example/hack?utm_source=listing">Register here</a>'
    assert tornado.to_event(row, data).url == "https://register.example/hack"


def test_party_flight_schema_and_empty_listing():
    assert party.parse_list(fixture("hackathonparty", "empty.html")) == []
    urls = party.parse_list(fixture("hackathonparty", "list.html"))
    assert urls == ["https://www.hackathonparty.com/hackathons/43"]
    node = party.parse_detail(fixture("hackathonparty", "detail.html"))
    event = party.to_event(node, urls[0])
    assert event.start.year == 2098 and event.format == "hybrid"
    assert event.organizer == "GitNation" and event.url == urls[0]  # never substitute organizer homepage
    assert "Amsterdam" in event.location
    assert party.to_event({**node, "endDate": "2020-01-01"}, urls[0]) is None


def test_open_rendered_contract_unverified_live():
    html = fixture("openhackathons", "rendered.html")
    urls = opened.event_urls(html)
    assert len(urls) == 1 and urls[0].startswith("https://www.openhackathons.org/s/siteevent/")
    event = opened.parse_detail(html, urls[0])
    assert event.start.year == 2099 and event.registration_deadline.year == 2098
    assert event.format == "online" and event.organizer == "Research Lab"
    assert event.url == "https://registration.example/hack" and event.kind == "unknown"
    assert opened.parse_detail(html.replace("2099", "2020"), urls[0]) is None
    assert opened.parse_detail(html.replace("Research Open Hackathon", "Research Bootcamp"), urls[0]) is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
