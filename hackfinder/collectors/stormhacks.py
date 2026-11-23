"""StormHacks: public Svelte HTML, edition year in the title."""
import re

from ._organizer_util import HTMLParser, body, collect_page, dates, make, registration, schema

SOURCE = {"id": "stormhacks", "name": "StormHacks", "url": "https://www.stormhacks.com/",
          "method": "api", "default_kind": "hackathon"}


def parse(html):
    if events := schema(html, SOURCE, location='SFU Burnaby, Canada', country='CA'):
        return events
    tree, text = HTMLParser(html), body(html)
    title = tree.css_first('title')
    year = re.search(r'\b20\d{2}\b', title.text() if title else '')
    date = re.search(r'\b(?:Oct|October)\s+\d{1,2}\s*\+\s*\d{1,2}\b', text, re.I)
    start, end = dates(date[0] + ' ' + year[0]) if year and date else dates(text)
    e = make(SOURCE, title.text() if title else 'StormHacks', registration(html, SOURCE['url']) or SOURCE['url'],
        start, end, text=text, location='Simon Fraser University, Burnaby, Canada', country='CA',
        fmt='in-person', organizer='SFU Surge')
    return [e] if e else []


def collect():
    return collect_page(SOURCE, parse)
