"""HackMeridian: public event JSON-LD and original application link."""
import re

from ._organizer_util import body, collect_page, schema
from ._signals_util import reward

SOURCE = {"id": "hackmeridian", "name": "HackMeridian", "url": "https://www.hackmeridian.com/",
          "method": "api", "default_kind": "hackathon"}


def parse(html):
    events = schema(html, SOURCE, location='Lisbon, Portugal', country='PT')
    prize = re.search(r'\$[\d,]+\s+across\s+\d+\s+winners', body(html))
    for e in events:
        if prize:
            e.prize = prize[0] + ' (USD equivalent paid in XLM)'
            e.signals.update(reward(prize[0]))
            e.prize_usd = e.signals.get('prize_amount')
    return events


def collect():
    return collect_page(SOURCE, parse)
