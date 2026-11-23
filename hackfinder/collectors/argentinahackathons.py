"""argentinahackathons.com: public country-network RSS/sitemap and Event JSON-LD."""
from ._country_sites import collect_site, event_urls as _event_urls, parse_event, to_event as _to_event

SOURCE = {"id": "argentinahackathons", "name": "Argentina Hackathons", "url": "https://argentinahackathons.com/",
          "method": "api", "default_kind": "hackathon"}
BASE = SOURCE["url"].rstrip("/")


def event_urls(*documents):
    return _event_urls(*documents, base=BASE)


def to_event(node, page_url):
    return _to_event(node, page_url, SOURCE["id"], "Argentina")


def collect():
    return collect_site(SOURCE, "Argentina")
