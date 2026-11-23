"""EDTH Commonspace calendar: constrained string fields in server-rendered bootstrap data."""
import json
import re
from urllib.parse import urljoin

from hackfinder.models import Event
from ._ecosystem_util import HACK, client, get, robots, text_tree, upcoming
from ._signals_util import geo, signals
from ._vertical_util import dt
from ._platforms_util import current

SOURCE = {'id': 'eurodefense', 'name': 'European Defense Tech Hub', 'url': 'https://events.eurodefense.tech/root',
          'method': 'api', 'default_kind': 'mixed'}


def field(text, key):
    m = re.search(r'(?<![\w])' + re.escape(key) + r':("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?)', text)
    return json.loads(m[1]) if m else None


def parse(html):
    result = {}
    for block in re.findall(r'\{handle:".*?(?=viewerJoined:|\{handle:|</script>)', html, re.S):
        title = field(block, 'name')
        if not title or not HACK.search(title) or 'isEvent:!0' not in block:
            continue
        start, end = dt(field(block, 'startDate')), dt(field(block, 'endDate'))
        if not start or not current(start, end) or field(block, 'status') in ('cancelled', 'finished'):
            continue
        slug = field(block, 'slug') or field(block, 'handle')
        place = field(block, 'label')
        n = field(block, 'memberCount')
        e = Event(source='eurodefense', source_id=field(block, 'handle'),
            url=urljoin(SOURCE['url'], '/' + slug), title=title, start=start, end=end,
            location=place, format='in-person' if place else 'unknown', participants=n,
            organizer='European Defense Tech Hub',
            signals=signals(registrations=n, **geo(field(block, 'lat'), field(block, 'lng'))))
        result[e.source_id] = e
    if not result and 'subAudiences:' not in html:
        raise RuntimeError('EDTH: public event bootstrap missing')
    return list(result.values())


def collect():
    with client(timeout=20) as c:
        robots(c, SOURCE['url'])
        events = parse(get(c, SOURCE['url']).text)
        for e in events:
            tree = text_tree(get(c, e.url).text)
            e.signals.update(signals(text=tree.text()))
            e.description = e.signals.get('text', '')[:500] or None
        return events
