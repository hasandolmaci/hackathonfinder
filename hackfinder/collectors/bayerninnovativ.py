"""Bayern Innovativ's complete upcoming calendar, keyword-filtered before detail fetch."""
from hackfinder.models import Event
from ._ecosystem_util import HACK, dates, listing, registration, text_tree, upcoming
from ._platforms_util import plain
from ._signals_util import signals

SOURCE = {'id': 'bayerninnovativ', 'name': 'Bayern Innovativ',
          'url': 'https://www.bayern-innovativ.de/events-termine/alle-events/', 'method': 'api', 'default_kind': 'mixed'}


def parse(html, url):
    tree = text_tree(html)
    h = tree.css_first('h1[itemprop="headline"]')
    if not h or not HACK.search(h.text()):
        return []
    header = h.parent
    start, end = dates(header.text())
    if not start:
        raise RuntimeError(f'Bayern Innovativ: event date missing at {url}')
    if not upcoming(start, end):
        return []
    location = header.css_first('.primary-location-icon')
    place = ', '.join(n.text(strip=True) for n in location.css('span') if 'Google' not in n.text()) if location else None
    image = tree.css_first('img.img-event')
    from urllib.parse import urljoin
    return [Event(source='bayerninnovativ', source_id=url, url=registration(tree, url) or url,
        title=plain(h.text()), start=start, end=end, description=plain(tree.text()),
        location=place, country='Germany' if place and 'Deutschland' in place else None,
        format='in-person' if place else 'online' if 'Online-Event' in header.text() else 'unknown',
        image=urljoin(url, image.attributes['src']) if image else None,
        organizer='Bayern Innovativ' if 'Bayern Innovativ' in tree.text() else None,
        signals=signals(text=tree.text()))]


def collect():
    return listing(SOURCE, 'a[href*="/events-termine/detail/"]', parse)
