"""HackOnVibe: public event JSON-LD and original application link."""
from ._organizer_util import collect_page, schema

SOURCE = {"id": "hackonvibe", "name": "HackOnVibe", "url": "https://hackonvibe.com/",
          "method": "api", "default_kind": "hackathon"}


def parse(html):
    events = schema(html, SOURCE, location=None, country=None)
    return events


def collect():
    return collect_page(SOURCE, parse)
