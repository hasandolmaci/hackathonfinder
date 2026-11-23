"""Tech: Europe server-rendered hackathon cards; original Luma application URL."""
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

from hackfinder.models import Event
from ._ecosystem_util import HTMLParser, MONTHS, client, get, registration, robots, text_tree, upcoming
from ._platforms_util import current, plain
from ._signals_util import signals

SOURCE = {'id': 'techeurope', 'name': 'Tech: Europe', 'url': 'https://hackathons.techeurope.io/',
          'method': 'api', 'default_kind': 'hackathon'}


def parse(html, url):
    tree = text_tree(html)
    h = tree.css_first('h1')
    if not h:
        raise RuntimeError('Tech: Europe: event heading missing')
    header = plain(h.parent.text(), 3000) or ''
    found = re.findall(r'(\d{1,2}) (\w+) (20\d{2}), (\d{2}):(\d{2})', header)
    stamps = [datetime(int(y), MONTHS[m.lower()], int(d), int(hh), int(mm), tzinfo=ZoneInfo('Europe/Berlin')).astimezone(timezone.utc)
              for d, m, y, hh, mm in found]
    if not stamps:
        raise RuntimeError('Tech: Europe: event dates missing')
    if not current(stamps[0], stamps[-1]):
        return []
    place = re.search(r'·\s*(.*?)(?:Prize pool:|$)', header)
    place = place[1].strip() if place else None
    cash = re.search(r'Prize pool:\s*€([\d,]+)', header)
    sponsors = [plain(a.css_first('strong').text()) for a in tree.css('a[href*="utm_medium=partner_page"]') if a.css_first('strong')]
    return [Event(source='techeurope', source_id=url.rstrip('/').split('/')[-1], title=plain(h.text()),
        url=registration(tree, url) or url, start=stamps[0], end=stamps[-1],
        format='online' if 'Online' in header else 'in-person' if place else 'unknown', location=place,
        country=place.rsplit(',', 1)[-1].strip() if place and ',' in place else None,
        organizer='Tech: Europe', prize=f'€{cash[1]}' if cash else None,
        kind='hackathon', confidence=0.9, classified_by='source',
        signals=signals(text=tree.text(), sponsors=sponsors or None,
            **({'prize_amount': float(cash[1].replace(',', '')), 'prize_currency': 'EUR'} if cash else {})))]


def collect():
    events = {}
    with client(timeout=20) as c:
        robots(c, SOURCE['url'])
        tree = HTMLParser(get(c, SOURCE['url']).text)
        if not tree.css('a[href^="/events/"]') and 'Upcoming hackathons' not in tree.text():
            raise RuntimeError('Tech: Europe: hackathon listing missing')
        for a in tree.css('a[href^="/events/"]'):
            # Upcoming cards say View & apply. Completed cards link to results.
            if 'View & apply' not in a.text():
                continue
            url = urljoin(SOURCE['url'], a.attributes['href'])
            events.update({e.url: e for e in parse(get(c, url).text, url)})
    return list(events.values())
