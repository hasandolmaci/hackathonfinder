"""Offline tests for the Dutch coverage: netherlandshackathons parser, Luma Dutch city match, Meetup/Eventbrite lists.

Run: python tests/test_netherlands.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackfinder.collectors import eventbrite, luma, meetup, netherlandshackathons as nh

FIX = ROOT / "tests" / "fixtures" / "netherlandshackathons"


def test_nh_parse():
    rss = (FIX / "rss.xml").read_text(encoding="utf-8")
    urls = nh.event_urls(rss)
    assert urls and all("/events/" in u and "/en/" not in u for u in urls)
    html = (FIX / "event.html").read_text(encoding="utf-8").replace("2027-01", "2098-01")
    node = nh.parse_event(html)
    ev = nh.to_event(node, urls[0])
    assert ev.kind == "game_jam" and ev.country == "Netherlands" and ev.location == "Breda, Netherlands"
    assert "eventbrite.nl/e/" in ev.url, ev.url  # the original registration URL, not the aggregator page
    assert ev.signals["paid_entry"] is True and ev.format == "in-person" and ev.start.year == 2098
    assert nh.to_event(nh.parse_event(html.replace("2098-01", "2020-01")), urls[0]) is None  # past


def test_luma_dutch_city_match():
    def entry(city):
        return {"event": {"geo_address_info": {"city": city, "full_address": f"Straat 1, {city}"}}}
    assert luma._in_city(entry("Den Haag"), "The Hague") and luma._in_city(entry("The Hague"), "Den Haag")
    assert luma._in_city(entry("'s-Hertogenbosch"), "Den Bosch")
    assert not luma._in_city(entry("Amsterdam"), "Den Haag")
    assert {"Breda", "Den Haag", "Amersfoort", "Haarlem"} <= set(luma.CITY_QUERIES)


def test_lists():
    assert {"netherlands", "netherlands--the-hague", "netherlands--arnhem"} <= set(eventbrite.CITIES)
    assert {"nl--Utrecht", "nl--The Hague", "nl--Breda"} <= set(meetup.LOCATIONS)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
