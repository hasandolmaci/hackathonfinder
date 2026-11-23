"""HackSpain: public event JSON-LD and original application link."""
import re

from ._organizer_util import body, collect_page, schema
from ._signals_util import money

SOURCE = {"id": "hackspain", "name": "HackSpain", "url": "https://hackspain.com/",
          "method": "api", "default_kind": "hackathon"}


def parse(html):
    events = schema(html, SOURCE, location='Madrid, Spain', country='ES')
    prize = re.search(r'\+?([\d.]+)€\s*en premios', body(html))
    for e in events:
        if prize:
            e.prize = prize[0]
            e.signals.update(money(prize[1].replace('.', ''), 'EUR'))
    return events


def collect():
    return collect_page(SOURCE, parse)
