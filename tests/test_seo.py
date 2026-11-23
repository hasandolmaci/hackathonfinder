"""Offline tests for the search-engine helpers (hackfinder/seo.py)."""
from hackfinder import seo


def test_rows_escape_and_fill_gaps():
    html = seo.rows([{"url": "https://e.org/?a=1&b=2", "title": "<b>Jam</b>", "kind": "game_jam", "format": "online",
                      "start": "2027-02-11T09:00:00Z", "score": None}])
    assert "&lt;b&gt;Jam&lt;/b&gt;" in html and "a=1&amp;b=2" in html
    assert "Feb 11, 2027" in html and "Worldwide" in html and "Game jam" in html


def test_pagination_links():
    assert seo.pages_nav("/hackathons", 1, 10) == ""
    first = seo.pages_nav("/hackathons", 1, 60)
    assert 'href="/hackathons?page=2" rel="next"' in first and "prev" not in first
    second = seo.pages_nav("/hackathons/ai", 2, 60)
    assert 'href="/hackathons/ai" rel="prev"' in second and "Page 2 of 3" in second


def test_presets_match_list_js_parameters():
    assert seo.preset(seo.LANDINGS["netherlands"][2]) == {"country": "NL"}
    assert seo.preset(seo.LANDINGS["game-jams"][2]) == {"kinds": "game_jam"}
    assert seo.preset(seo.LANDINGS["online"][2]) == {"format": "online"}


def test_site_url_and_robots(monkeypatch):
    monkeypatch.delenv("HF_SITE_URL", raising=False)
    assert seo.site_url("http://hackfinder.vercel.app/") == "https://hackfinder.vercel.app"
    assert seo.site_url("http://localhost:8000/") == "http://localhost:8000"
    monkeypatch.setenv("HF_SITE_URL", "https://hackfinder.eu/")
    assert seo.site_url("http://x.vercel.app/") == "https://hackfinder.eu"
    assert "Sitemap: https://hackfinder.eu/sitemap.xml" in seo.robots("https://hackfinder.eu")


def test_browse_links_skip_thin_pages():
    links = seo.browse_links({"ai": 40, "netherlands": 2}, current="ai")
    assert "/hackathons/ai" in links and 'aria-current=page' in links and "netherlands" not in links
