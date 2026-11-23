"""No public search: discover keyword event roots in the public sitemap, then Event microdata."""
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from hackfinder.models import Event
from ._ecosystem_util import HACK, NOISE, HTMLParser, MAX_PAGES, client, get, robots, upcoming, warn_limit
from ._platforms_util import plain
from ._signals_util import signals
from ._vertical_util import dt

SOURCE = {'id': 'aanmelder', 'name': 'aanmelder.nl', 'url': 'https://www.aanmelder.nl/sitemap.xml',
          'method': 'api', 'default_kind': 'mixed'}


def event_urls(xml):
    result = set()
    for n in ET.fromstring(xml).iter():
        if n.tag.rsplit('}', 1)[-1] != 'loc' or not n.text:
            continue
        p = urlsplit(n.text)
        slug = p.path.strip('/').split('/')[0]
        if p.hostname == 'www.aanmelder.nl' and HACK.search(slug) and not NOISE.search(slug):
            result.add(f'https://www.aanmelder.nl/{slug}')
    return sorted(result)


def parse(html, url):
    tree = HTMLParser(html)
    root = tree.css_first('[itemtype$="Event"]')
    if not root:
        return []  # Removed/unpublished registration pages can remain in the sitemap.
    def prop(key, node=None):
        n = (node or root).css_first(f'[itemprop="{key}"]')
        return (n.attributes.get('content') or n.attributes.get('href') or n.text(strip=True)) if n else None
    title = prop('name') or ''
    if not HACK.search(title) or NOISE.search(title) or 'Cancelled' in (prop('eventStatus') or ''):
        return []
    start, end = dt(prop('startDate')), dt(prop('endDate'))
    if not start or not upcoming(start, end):
        return []
    loc = root.css_first('[itemprop="location"]')
    place = prop('address', loc) if loc else None
    if place and place.lower() in ('to be announced', 'n.t.b.', 'tba', 'nog niet bekend'):
        place = None
    org = root.css_first('[itemprop="organizer"]')
    offer = root.css_first('[itemprop="offers"]')
    image = root.css_first('[itemprop="image"]')
    online = 'OnlineEvent' in (prop('eventAttendanceMode') or '')
    from urllib.parse import urljoin
    return [Event(source='aanmelder', source_id=url, title=title, url=urljoin(url, prop('url', offer)) if offer and prop('url', offer) else url,
        start=start, end=end, description=plain(prop('description')),
        image=urljoin(url, image.attributes.get('src', '')) if image else None,
        location=None if online else place, format='online' if online else 'in-person' if 'Offline' in (prop('eventAttendanceMode') or '') else 'unknown',
        country=prop('addressCountry', loc) if loc else None, organizer=prop('name', org) if org else None,
        signals=signals(text=prop('description'), paid_entry=float(prop('price', offer)) > 0 if offer and prop('price', offer) else None))]


def collect():
    events = {}
    with client(timeout=20) as c:
        robots(c, SOURCE['url'])
        queue, seen, urls = [SOURCE['url']], set(), set()
        for _ in range(MAX_PAGES):
            if not queue:
                break
            page = queue.pop(0)
            if page in seen:
                continue
            seen.add(page)
            xml = get(c, page).text
            root = ET.fromstring(xml)
            if root.tag.endswith('sitemapindex'):
                queue.extend(n.text for n in root.iter() if n.tag.endswith('loc') and n.text not in seen)
            else:
                urls.update(event_urls(xml))
        else:
            if queue:
                warn_limit(__name__, 'sitemaps')
        for url in sorted(urls):
            try:
                events.update({e.url: e for e in parse(get(c, url).text, url)})
            except Exception as exc:
                import httpx
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (404, 410):
                    continue
                raise
    return list(events.values())
