"""Brainport Eindhoven public upcoming calendar, internal and original external links."""
import re

from hackfinder.models import Event
from ._ecosystem_util import HACK, dates, listing, parse_schema, registration, text_tree, upcoming
from ._platforms_util import plain
from ._signals_util import signals

SOURCE = {'id': 'brainport', 'name': 'Brainport Eindhoven', 'url': 'https://brainporteindhoven.com/en/events',
          'method': 'api', 'default_kind': 'mixed'}


def parse(html, url):
    events = parse_schema(html, 'brainport', url)
    if events:
        return events
    tree = text_tree(html)
    h = tree.css_first('h1')
    if not h or not HACK.search(h.text()):
        return []
    text = tree.text(separator=' ', strip=True)
    # Brainport labels omit the year; require an explicit full date in the article.
    start, end = dates(text)
    if not start:
        raise RuntimeError(f'Brainport: explicit event year/date missing at {url}')
    if not upcoming(start, end):
        return []
    loc = re.search(r'Location:\s*(.*?)(?:Sign up|Register|Date:|$)', text)
    return [Event(source='brainport', source_id=url, url=registration(tree, url) or url,
        title=plain(h.text()), description=plain(text), start=start, end=end,
        format='in-person' if loc else 'unknown', location=loc[1].strip() if loc else None,
        signals=signals(text=text))]


def collect():
    return listing(SOURCE, '.media-overview-item--event a.media-overview-item__inner[href]', parse)
