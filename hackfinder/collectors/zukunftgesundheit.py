"""Future Health Hackathon: public Event JSON-LD and original Pretix registration."""
from ._ecosystem_util import HTMLParser, client, get, parse_schema, robots

SOURCE = {'id': 'zukunftgesundheit', 'name': 'Zukunft Gesundheit', 'url': 'https://zukunftgesundhe.it/',
          'method': 'api', 'default_kind': 'hackathon'}


def parse(html):
    events = parse_schema(html, 'zukunftgesundheit', SOURCE['url'], 'hackathon')
    sponsors = list(dict.fromkeys(n.attributes['alt'] for n in HTMLParser(html).css('img[src*="/partners/"][alt]') if n.attributes['alt']))
    for e in events:
        if sponsors:
            e.signals['sponsors'] = sponsors
    return events


def collect():
    with client(timeout=20) as c:
        robots(c, SOURCE['url'])
        return parse(get(c, SOURCE['url']).text)
