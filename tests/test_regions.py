"""Country/region normalization and filters: python tests/test_regions.py (offline, temporary SQLite)."""
from __future__ import annotations

from datetime import timedelta
import importlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_GEOCODE_ONLINE", "0")  # no network in tests
os.environ.pop("DATABASE_URL", None)

from fastapi.testclient import TestClient
from hackfinder import db, store, worker
from hackfinder.models import Event
from hackfinder.regions import COUNTRIES, REGIONS, country_code, resolve

app_module = importlib.import_module("hackfinder.app")


def event(title="Build Night", **kwargs):
    return Event(**{"source": "luma", "url": "https://luma.com/" + title.replace(" ", "-"), "title": title,
                    "kind": "hackathon", "format": "in-person", **kwargs})


def collector(cid, rows):
    return SimpleNamespace(SOURCE={"id": cid, "name": cid.title(), "method": "api", "default_kind": "mixed"},
                           collect=lambda: rows)


def test_normalization():
    cases = [("Amsterdam, Netherlands", None, "NL", "europe"), ("Eindhoven, NL", None, "NL", "europe"),
             ("Den Haag, Nederland", None, "NL", "europe"), ("San Francisco, CA, USA", None, "US", "north_america"),
             ("London, UK", None, "GB", "europe"), ("Bengaluru, India", None, "IN", "asia"),
             ("São Paulo, Brazil", None, "BR", "latin_america"), ("Dubai, UAE", None, "AE", "middle_east"),
             ("Istanbul", "Türkiye", "TR", "middle_east"), ("Berlin", "Deutschland", "DE", "europe"),
             ("Lagos", "nl", "NL", "europe"), ("Nairobi, Kenya", None, "KE", "africa"),
             ("Sydney, Australia", None, "AU", "oceania"), ("Austin, TX", None, "US", "north_america"),
             ("Toronto, Canada", None, "CA", "north_america"), ("Nowhereville", None, None, None)]
    for location, country, code, region in cases:
        assert resolve(event(location=location, country=country), use_geo=False) == (code, region), location
    assert resolve(event(format="online", location="Online"), use_geo=False) == (None, "online")
    assert resolve(event(format="in-person", location="Online"), use_geo=False) == (None, "online")
    assert resolve(event(location="Utrecht"))[0] == "NL"  # GeoNames city lookup (worker path)
    assert country_code("USA") == "US" and country_code("UK") == "GB" and country_code("xx") is None
    assert {r for _, r in COUNTRIES.values()} | {"online"} == set(REGIONS)
    print("PASS country/region normalization")


def test_api():
    now = store.utcnow()
    rows = [event("Amsterdam Hackathon", start=now + timedelta(days=3), location="Amsterdam, Netherlands"),
            event("Berlin Hackathon", start=now + timedelta(days=4), location="Berlin, Germany"),
            event("Hague Hackathon", start=now + timedelta(days=5), location="Den Haag, Nederland"),
            event("Mumbai Hackathon", start=now + timedelta(days=6), location="Mumbai, India"),
            event("Remote Hackathon", start=now + timedelta(days=7), format="online", location="Online"),
            event("Old Hackathon", start=now - timedelta(days=9), end=now - timedelta(days=8), location="Paris, France")]
    with tempfile.TemporaryDirectory() as directory:
        os.environ["HF_DB_PATH"] = str(Path(directory) / "test.db")
        db.init()
        db.init()  # idempotent column migration
        app_module.clear_cache()
        with patch("hackfinder.worker.refresh_rates"):
            worker.run("quick", collectors={"luma": collector("luma", rows)})
        with TestClient(app_module.app) as client:
            def titles(query):
                return {e["title"] for e in client.get("/api/hackathons?" + query).json()["events"]}
            assert titles("country=NL") == {"Amsterdam Hackathon", "Hague Hackathon"}
            assert titles("country=nl,de") == {"Amsterdam Hackathon", "Hague Hackathon", "Berlin Hackathon"}
            assert titles("region=asia") == {"Mumbai Hackathon"}
            assert titles("region=europe,asia") == {"Amsterdam Hackathon", "Hague Hackathon", "Berlin Hackathon", "Mumbai Hackathon"}
            assert titles("region=online") == {"Remote Hackathon"}
            assert titles("region=europe&country=DE") == {"Berlin Hackathon"}
            assert titles("region=bogus,xx&country=ZZ") == titles("")  # unknown ids are ignored
            ams = next(e for e in client.get("/api/hackathons?country=NL").json()["events"] if e["title"] == "Amsterdam Hackathon")
            assert (ams["country_code"], ams["region"], ams["country_name"]) == ("NL", "europe", "Netherlands")
            data = client.get("/api/regions").json()
            assert [r["id"] for r in data["regions"]] == list(REGIONS)
            counts = {r["id"]: r["count"] for r in data["regions"]}
            assert counts["europe"] == 3 and counts["asia"] == 1 and counts["online"] == 1 and counts["africa"] == 0
            assert data["countries"][0] == {"code": "NL", "name": "Netherlands", "region": "europe", "count": 2}
            assert {c["code"] for c in data["countries"]} == {"NL", "DE", "IN"}  # past + online excluded
            assert client.get("/api/regions?format=online").json()["regions"][-1]["count"] == 1
            assert client.get("/api/regions?days=bad").status_code == 422
        with db.connect() as conn:  # before the first rescore: derived from the event data
            conn.execute("UPDATE events SET country_code = NULL, region = NULL")
        app_module.clear_cache()
        with TestClient(app_module.app) as client:
            assert {r["id"]: r["count"] for r in client.get("/api/regions").json()["regions"]}["europe"] == 3
    print("PASS API region/country filters and /api/regions counts")


def test_sql_and_web_imports():
    import inspect
    for source in (inspect.getsource(app_module._listing), inspect.getsource(app_module._region_counts)):
        assert "region IN (" in source or "country_code" in source
    assert "?" in inspect.getsource(app_module._listing) and "%" not in "".join(
        line for line in inspect.getsource(app_module._region_counts).splitlines() if "WHERE" in line)
    code = (ROOT / "hackfinder" / "regions.py").read_text(encoding="utf-8")
    assert "import geonamescache" not in code and "\nfrom . import geo" not in code.split("def _from_city")[0]
    with patch.dict(sys.modules, {"geonamescache": None}):
        assert resolve(event(location="Amsterdam, Netherlands"))[0] == "NL"
    print("PASS Postgres-safe placeholders; region lookup does not need GeoNames")


if __name__ == "__main__":
    test_normalization()
    test_api()
    test_sql_and_web_imports()
    print("All region tests passed (offline).")
