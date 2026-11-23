"""DubHacks: current flagship dates and hacker application URL."""
from ._organizer_util import body, collect_page, dates, make, registration, schema

SOURCE = {"id": "dubhacks", "name": "DubHacks", "url": "https://dubhacks.co/",
          "method": "api", "default_kind": "hackathon"}


def parse(html):
    if events := schema(html, SOURCE, location='University of Washington, Seattle, United States', country='US'):
        return events
    text = body(html)
    start, end = dates(text)
    e = make(SOURCE, f'DubHacks {start.year}' if start else 'DubHacks',
        registration(html, SOURCE['url']) or SOURCE['url'], start, end, text=text,
        location='University of Washington, Seattle, United States', country='US', fmt='in-person',
        organizer='DubHacks, University of Washington')
    return [e] if e else []


def collect():
    return collect_page(SOURCE, parse)
