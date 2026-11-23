"""SYE: public event JSON-LD and original application link."""
import re

from ._organizer_util import HTMLParser, body, collect_page, schema
from ._signals_util import money

SOURCE = {"id": "sye", "name": "SYE", "url": "https://sweyoung.com/hackathon/",
          "method": "api", "default_kind": "hackathon"}


def parse(html):
    events = schema(html, SOURCE, location='Stockholm, Sweden', country='SE')
    total = re.search(r'\b(\d{1,3}(?: \d{3})+|\d+)\+?\s*kr\s+in prizes', body(html))
    themes = [n.text().strip() for n in HTMLParser(html).css('#tracks h3')]
    for e in events:
        if themes:
            e.signals['themes'] = themes
        if total:
            e.prize = total[0] + ' (cash and noncash)'
            e.signals.update(money(total[1].replace(' ', '').rstrip('+'), 'SEK'))
            e.signals['prize_noncash'] = True
    return events


def collect():
    return collect_page(SOURCE, parse)
