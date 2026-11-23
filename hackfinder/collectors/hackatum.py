"""hackaTUM's next edition, from its public WordPress landing page."""
import re

from hackfinder.models import Event
from ._ecosystem_util import client, dates, get, registration, robots, text_tree, upcoming
from ._signals_util import signals
from ._platforms_util import plain

SOURCE = {'id': 'hackatum', 'name': 'hackaTUM', 'url': 'https://hack.tum.de/',
          'method': 'api', 'default_kind': 'hackathon'}


def parse(html):
    tree = text_tree(html)
    text = plain(tree.text(), 20000) or ''
    start, end = dates(text[:1000])
    if not start:
        raise RuntimeError('hackaTUM: next edition date missing')
    if not upcoming(start, end):
        return []
    sponsors = [n.attributes['alt'] for n in tree.css('img[alt]')
                if re.search(r'sponsor|partner', str(n.attributes), re.I) and n.attributes['alt']]
    return [Event(source='hackatum', source_id=str(start.year), title=f'hackaTUM {start.year}',
        url=registration(tree, SOURCE['url']) or SOURCE['url'], start=start, end=end,
        description=plain(text[text.find('About us'):]), format='in-person', location='Munich, Germany', country='Germany',
        organizer='Technical University of Munich', kind='hackathon', confidence=0.9, classified_by='source',
        signals=signals(text=text, sponsors=sponsors or None))]


def collect():
    with client(timeout=20) as c:
        robots(c, SOURCE['url'])
        return parse(get(c, SOURCE['url']).text)
