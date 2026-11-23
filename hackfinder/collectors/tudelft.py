"""TU Delft calendar: exhaust page links, keyword-filter cards, read detail Event JSON-LD."""
from urllib.parse import urljoin

from ._ecosystem_util import HACK, NOISE, HTMLParser, MAX_PAGES, client, get, parse_schema, robots, warn_limit

SOURCE = {'id': 'tudelft', 'name': 'TU Delft', 'url': 'https://www.tudelft.nl/en/about-tu-delft/calendar',
          'method': 'api', 'default_kind': 'mixed'}


def parse(html, url):
    events = parse_schema(html, 'tudelft', url)
    for e in events:
        e.organizer = e.organizer or 'TU Delft'
    return events


def collect():
    events, seen, details, queue = {}, set(), set(), [SOURCE['url']]
    with client(timeout=20) as c:
        robots(c, SOURCE['url'])
        for _ in range(MAX_PAGES):
            if not queue:
                break
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            tree = HTMLParser(get(c, url).text)
            if not tree.css('a[href*="/en/events/"], a[href*="/en/evenementen/"]'):
                if '0 results' in tree.text():
                    break
                raise RuntimeError('TU Delft: calendar event links missing')
            for a in tree.css('a[href*="/en/events/"], a[href*="/en/evenementen/"]'):
                href = urljoin(url, a.attributes['href'])
                if href in details or not HACK.search(a.text()) or NOISE.search(a.text()):
                    continue
                details.add(href)
                events.update({e.url: e for e in parse(get(c, href).text, href)})
            for a in tree.css('a[href^="/en/about-tu-delft/calendar/page-"]'):
                href = urljoin(url, a.attributes['href'])
                if href not in seen and href not in queue:
                    queue.append(href)
        else:
            if queue:
                warn_limit(__name__)
    return list(events.values())
