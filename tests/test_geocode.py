"""Geocoding: source coordinates first, better offline parsing, the cached Nominatim fallback (HTTP mocked)."""
from __future__ import annotations

from datetime import timedelta
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["HF_GEOCODE_ONLINE"] = "0"  # online lookups are enabled per test, always with mocked HTTP

from hackfinder import db, geo, geocoder, store
from hackfinder.collectors import _signals_util, luma, meetup
from hackfinder.models import Event


def event(**kwargs):
    base = dict(source="x", url="https://x/1", title="Build Night", format="in-person")
    return Event(**{**base, **kwargs})


def city(text, country=None):
    found = geo.match(text, country)
    return found and (found["name"], found["country_code"])


def hit(lat="1.5", lon="2.5", cc="de", name="Somewhere"):
    return [{"lat": lat, "lon": lon, "display_name": name, "address": {"country_code": cc}}]


class Http:
    """Stands in for httpx.get; records calls."""

    def __init__(self, *replies, status=200):
        self.replies, self.status, self.calls = list(replies), status, []

    def __call__(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        response = MagicMock(status_code=self.status)
        response.json.return_value = self.replies.pop(0) if self.replies else []
        response.raise_for_status.side_effect = None if self.status < 400 else RuntimeError("http")
        return response


def run(events, http, *, max_lookups=150, enable=True, directory=None):
    """locate() every event through a fresh Geocoder on a temp DB; returns (results, geocoder, sleeps)."""
    sleeps = []
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["HF_DB_PATH"] = str(Path(directory or tmp) / "t.db")
        db.init()
        with db.connect() as conn, patch.dict(os.environ, {"HF_GEOCODE_ONLINE": "1" if enable else "0"}), \
                patch("httpx.get", http), patch.object(geocoder, "_sleep", sleeps.append):
            g = geocoder.Geocoder(conn, max_lookups)
            return [geo.locate(e, g) for e in events], g, sleeps


def test_offline_parsing():
    assert city("Bangalore Urban, Karnataka, India") == ("Bengaluru", "IN")
    assert city("New Administrative Capital, Cairo Governorate, Egypt") == ("Cairo", "EG")
    assert city("Den Haag, Netherlands") == ("The Hague", "NL")
    assert city("Greater London") == ("London", "GB")
    assert city("Savannnah, GA") == ("Savannah", "US")  # typo, accepted because the state fixes the country
    assert city("Springfield, IL")[1] == "US" and geo.match("Springfield, IL")["admin1code"] == "IL"
    assert geo.match("Paris, TX")["country_code"] == "US" and city("Paris", "France") == ("Paris", "FR")
    assert city("Toronto, ON, Canada") == ("Toronto", "CA")
    assert city("Mumbai, IN") == ("Mumbai", "IN")  # IN is also a US state code, but no Mumbai in Indiana
    assert city("Georgia Tech, Atlanta, GA") == ("Atlanta", "US")
    # towns and venues GeoNames (population > 15000) does not know stay unresolved offline, never wrong
    for text in ["Furtwangen, Germany", "Rotkreuz, Switzerland", "Msida, Malta", "Magnolia, AR, United States",
                 "East Greenwich, RI", "MSU - STEM Building", "The College of New Jersey", "Pennovation Works",
                 "UBC Sauder (Demo Day)", "Museo Del Acero Horno 3", "RPI DCC", "XDC"]:
        assert city(text) is None, text
    assert geo.geocode("Amsterdam, Netherlands")[0] > 52 and geo.geocode("Amsterdam", format="online") == (None, None)
    print("PASS offline parsing: parts, region words, aliases, state codes, typos, no airport-code false matches")


def test_markers_not_geocoded():
    for text in ["REMOTE", "Online", "virtual", "TBD", "tba", "Test Location", " ", None]:
        assert geo.placeholder(text) and geo.match(text) is None and geo.geocode(text) == (None, None)
    http = Http(hit())
    results, g, _ = run([event(location=t) for t in ["REMOTE", "Test Location", "TBD", None]], http)
    assert results == [(None, None, None)] * 4 and not http.calls and g.requests == 0
    print("PASS junk and online markers are never geocoded")


def test_signals_first():
    http = Http(hit())
    signalled = event(location="Amsterdam, Netherlands", signals={"lat": 10.5, "lon": 20.5})
    assert run([signalled], http)[0] == [(10.5, 20.5, None)] and not http.calls
    for bad in [{"lat": 0, "lon": 0}, {"lat": 91, "lon": 5}, {"lat": "x", "lon": 5}, {"lat": 5}]:
        lat, lon, _ = geo.locate(event(location="Amsterdam, Netherlands", signals=bad))
        assert 52 < lat < 53, bad  # invalid source coordinates fall back to the offline city
    assert geo.locate(event(location="Berlin", format="online", signals={"lat": 1.0, "lon": 2.0})) == (None, None, None)
    print("PASS signals lat/lon win when valid; invalid ones fall back; online events get none")


def test_source_collectors_capture_coordinates():
    assert _signals_util.geo("52.5", "13.4", " Mitte,  Berlin ") == {"lat": 52.5, "lon": 13.4, "address": "Mitte, Berlin"}
    assert _signals_util.geo(0, 0) == {} and _signals_util.geo(None, 5) == {} and _signals_util.geo(95, 5) == {}
    entry = {"event": {"name": "Hack", "url": "h", "start_at": "2099-01-01T10:00:00.000Z", "location_type": "offline",
                       "coordinate": {"latitude": 51.41, "longitude": 5.45},
                       "geo_address_info": {"city": "Eindhoven", "country": "Netherlands", "full_address": "Holst Centre, Eindhoven"}},
             "hosts": [], "calendar": {}}
    e = luma._event(entry)
    assert (e.signals["lat"], e.signals["lon"], e.signals["address"]) == (51.41, 5.45, "Holst Centre, Eindhoven")
    venue = {"name": "Hub", "city": "Austin", "lat": 30.27, "lon": -97.74}
    assert meetup._signals({}, {}, "", 3, venue)["lat"] == 30.27
    assert "lat" not in meetup._signals({}, {}, "", 3, {"lat": 0, "lon": 0})
    from hackfinder.collectors._signals_util import source_signals
    row = {"primary_venue": {"address": {"latitude": "52.5", "longitude": "13.39", "localized_address_display": "Zimmerstr 78"}}}
    assert source_signals("eventbrite", row)["lat"] == 52.5
    ld = {"location": {"geo": {"latitude": "40.1", "longitude": "-74.2"}}}
    assert source_signals("eventbrite", {}, ld)["lon"] == -74.2
    print("PASS Luma, Meetup and Eventbrite keep source coordinates in signals")


def test_online_lookup_and_cache():
    ev = event(location="Furtwangen, Germany", country="Germany")
    http = Http(hit("48.05", "8.2", "de", "Furtwangen im Schwarzwald"))
    with tempfile.TemporaryDirectory() as directory:
        results, g, _ = run([ev, ev], http, directory=directory)
        assert results == [(48.05, 8.2, "DE")] * 2 and len(http.calls) == 1 and g.requests == 1
        url, params, headers = http.calls[0]
        assert url == geocoder.URL and params["format"] == "jsonv2" and params["limit"] == 1 and params["addressdetails"] == 1
        assert params["q"] == "furtwangen, germany" and params["countrycodes"] == "de"
        assert headers["User-Agent"] == "Hackfinder/1.0 (open-source hackathon finder)"
        # a second run on the same DB is served from the cache
        again = Http()
        assert run([ev], again, directory=directory)[0] == [(48.05, 8.2, "DE")] and not again.calls
    print("PASS online lookup is normalized, sent politely and cached")


def test_country_added_and_contradiction_rejected():
    http = Http(hit("33.6", "-95.5", "us", "Paris, Texas"))
    results, _, _ = run([event(location="Zeta Hall", country="France")], http)
    assert http.calls[0][1]["q"] == "zeta hall, france" and results == [(None, None, None)]  # a Texas answer for France
    results, _, _ = run([event(location="Hub X", country=None)], Http(hit("1", "2", "nl")))
    assert results == [(1.0, 2.0, "NL")]  # no known country: accepted, and the code is returned for regions
    print("PASS country appended to the query; contradicting results rejected")


def test_coarse_and_acronym_results_rejected():
    coarse = [dict(hit()[0], addresstype="county")]
    http = Http(coarse)
    assert run([event(location="Bradford, PA, United States")], http)[0] == [(None, None, None)] and len(http.calls) == 1
    http = Http(hit())
    assert run([event(location="XDC")], http)[0] == [(None, None, None)] and not http.calls  # short acronym, no country
    assert run([event(location="XDC", country="Germany")], Http(hit()))[0] == [(1.5, 2.5, "DE")]
    print("PASS county/state/country-level results and bare acronyms are not used")


def test_cache_miss_error_expiry():
    ev = event(location="Nowhere Hall, Germany")
    with tempfile.TemporaryDirectory() as directory:
        http = Http([])
        assert run([ev], http, directory=directory)[0] == [(None, None, None)] and len(http.calls) == 1
        again = Http(hit("1", "2", "de"))
        assert run([ev], again, directory=directory)[0] == [(None, None, None)] and not again.calls  # miss cached
        with db.connect() as conn:  # a 29-day-old miss is still valid, a 31-day-old one is retried
            for days, calls in ((29, 0), (31, 1)):
                stamp = (geocoder.utcnow() - timedelta(days=days)).isoformat()
                conn.execute("UPDATE geocode_cache SET fetched_at = ?", (stamp,))
                http = Http(hit("1", "2", "de"))
                with patch("httpx.get", http), patch.dict(os.environ, {"HF_GEOCODE_ONLINE": "1"}), patch.object(geocoder, "_sleep"):
                    g = geocoder.Geocoder(conn, 5)
                    out = g.lookup(ev)
                assert len(http.calls) == calls, days
            assert out == (1.0, 2.0, "DE")
    ev2 = event(location="Errorville, Germany")
    with tempfile.TemporaryDirectory() as directory:
        failing = Http(status=500)
        assert run([ev2], failing, directory=directory)[0] == [(None, None, None)]
        os.environ["HF_DB_PATH"] = str(Path(directory) / "t.db")
        with db.connect() as conn:
            assert conn.fetchone("SELECT status FROM geocode_cache")["status"] == "error"
            for days, calls in ((0, 0), (2, 1)):  # errors are retried after one day
                conn.execute("UPDATE geocode_cache SET fetched_at = ?", ((geocoder.utcnow() - timedelta(days=days)).isoformat(),))
                http = Http(hit("3", "4", "de"))
                with patch("httpx.get", http), patch.dict(os.environ, {"HF_GEOCODE_ONLINE": "1"}):
                    geocoder.Geocoder(conn, 5).lookup(ev2)
                assert len(http.calls) == calls, days
    print("PASS misses cached 30 days, errors 1 day, expiry retries")


def test_rate_limit_cap_and_switch():
    events = [event(location=f"Hall {n}, Germany") for n in range(5)]
    http = Http(*[hit() for _ in range(5)])
    results, g, sleeps = run(events, http, max_lookups=3)
    assert len(http.calls) == 3 and g.requests == 3  # the cap
    assert [r[0] for r in results] == [1.5, 1.5, 1.5, None, None]
    assert len(sleeps) == 2 and all(1.0 <= s <= geocoder.MIN_INTERVAL for s in sleeps)  # 1.1 s between requests
    assert geocoder.MIN_INTERVAL == 1.1
    off = Http(hit())
    assert run(events, off, enable=False)[0] == [(None, None, None)] * 5 and not off.calls  # HF_GEOCODE_ONLINE=0
    blocked = Http(status=429)
    _, g, _ = run(events, blocked)
    assert len(blocked.calls) == 1 and g.stopped  # a refusal stops the run
    with patch.dict(os.environ, {"HF_GEOCODE_MAX": "7"}):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["HF_DB_PATH"] = str(Path(tmp) / "t.db")
            db.init()
            with db.connect() as conn:
                assert geocoder.Geocoder(conn).max == 7
    print("PASS 1.1 s between requests, per-run cap, HF_GEOCODE_ONLINE=0, stop on refusal")


def test_rescore_pipeline():
    """remerge/rescore: source coordinates, GeoNames, then the online fallback (active events only), and the country."""
    now = store.utcnow()
    soon = now + timedelta(days=5)
    events = [event(source_id="a", url="https://x/a", title="Alpha Hackathon", start=soon, location="Anywhere", signals={"lat": 12.5, "lon": 34.5}),
              event(source_id="b", url="https://x/b", title="Beta Robotics Marathon", start=soon, location="Amsterdam, Netherlands"),
              event(source_id="c", url="https://x/c", title="Gamma Climate Sprint", start=soon, location="Furtwangen"),
              event(source_id="d", url="https://x/d", title="Delta Quantum Challenge 2027", start=soon, location="TBD")]
    with tempfile.TemporaryDirectory() as directory:
        os.environ["HF_DB_PATH"] = str(Path(directory) / "t.db")
        db.init()
        http = Http(hit("48.05", "8.2", "de", "Furtwangen"))
        with db.connect() as conn, patch.dict(os.environ, {"HF_GEOCODE_ONLINE": "1"}), patch("httpx.get", http), \
                patch.object(geocoder, "_sleep"):
            store.upsert_sources(conn, "x", "s", [(e, e) for e in events], now)
            store.remerge(conn, now, reclassify_rows=False)
            rows = {r["title"][:5]: r for r in conn.fetchall("SELECT title, lat, lon, country_code FROM events")}
        assert (rows["Alpha"]["lat"], rows["Alpha"]["lon"]) == (12.5, 34.5)
        assert 52 < rows["Beta "]["lat"] < 53 and rows["Beta "]["country_code"] == "NL"
        assert (rows["Gamma"]["lat"], rows["Gamma"]["country_code"]) == (48.05, "DE")
        assert rows["Delta"]["lat"] is None and len(http.calls) == 1
    print("PASS remerge uses signals, offline, then online results (with country)")


if __name__ == "__main__":
    test_offline_parsing()
    test_markers_not_geocoded()
    test_signals_first()
    test_source_collectors_capture_coordinates()
    test_online_lookup_and_cache()
    test_country_added_and_contradiction_rejected()
    test_coarse_and_acronym_results_rejected()
    test_cache_miss_error_expiry()
    test_rate_limit_cap_and_switch()
    test_rescore_pipeline()
    print("All geocode tests passed (offline, HTTP mocked).")
