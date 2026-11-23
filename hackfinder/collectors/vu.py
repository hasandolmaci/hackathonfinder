"""VU Amsterdam's own public Azure-search proxy, paginated with top/skip."""
import re
import time
from datetime import timezone
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

from hackfinder.models import Event
from ._ecosystem_util import HACK, NOISE, MAX_PAGES, client, get, robots, text_tree, upcoming, warn_limit
from ._platforms_util import current, plain
from ._signals_util import signals
from ._vertical_util import dt

SOURCE = {'id': 'vu', 'name': 'VU Amsterdam', 'url': 'https://vu.nl/en/events',
          'method': 'api', 'default_kind': 'mixed'}
API = 'https://vu.nl/api/search'
QUERY = 'hack* OR hakaton OR buildathon OR datathon OR ideathon OR ctf OR "capture the flag" OR "programming contest" OR programmeerwedstrijd OR "game jam" OR NWERC'


def local(value):
    parsed = dt(value)
    # SubTitle contains local wall times with no offset, unlike LastFetched.
    return parsed.replace(tzinfo=None).replace(tzinfo=ZoneInfo('Europe/Amsterdam')).astimezone(timezone.utc) if parsed else None


def parse(row, html=''):
    title = row.get('Title') or ''
    if not HACK.search(title + ' ' + (row.get('IntroText') or '')) or NOISE.search(title):
        return None
    stamps = (row.get('SubTitle') or '').split('|')
    start, end = local(stamps[0]), local(stamps[-1])
    if not start or not current(start, end):
        return None
    tree = text_tree(html)
    text = plain(tree.text(separator=' ', strip=True), 15000) or row.get('IntroText') or ''
    # Keep event evidence ahead of navigation/search labels.
    at = text.find(title)
    if at >= 0:
        text = text[at:]
    org = re.search(r'Organised by\s+(.*?)(?:Language|Quick links|$)', text)
    place = ', '.join(row.get('Details', [])[:1]) or None
    url = urljoin(SOURCE['url'], row['Url'])
    for a in tree.css('a[href]'):
        if re.search(r'sign up|register', a.text(), re.I) and a.attributes['href'].startswith('https://'):
            url = a.attributes['href']
            break
    return Event(source='vu', source_id=row.get('Id'), title=title, url=url, start=start, end=end,
        description=plain(row.get('IntroText')), image=row.get('ImageUrl'), location=place,
        country='Netherlands' if place and 'online' not in place.lower() else None,
        format='online' if place and 'online' in place.lower() else 'in-person' if place else 'unknown',
        organizer=org[1].strip() if org else 'VU Amsterdam', signals=signals(text=text))


def collect():
    events, seen = {}, set()
    with client(timeout=20) as c:
        robots(c, SOURCE['url'])
        for page in range(MAX_PAGES):
            time.sleep(1.1)
            r = c.post(API, headers={'index': 'vunl', 'api-version': '2020-06-30'}, json={
                'search': QUERY, 'queryType': 'full', 'filter': "Language eq 'en' and ItemType/any(c: c eq 'Agenda')",
                'top': 50, 'skip': page * 50, 'count': True})
            if r.status_code in (401, 403, 429):
                raise RuntimeError(f'blocked: HTTP {r.status_code} at {API}')
            r.raise_for_status()
            data = r.json()
            if not isinstance(data.get('value'), list):
                raise RuntimeError('VU: public search response missing value')
            fresh = [row for row in data['value'] if row.get('Id') not in seen]
            seen.update(row.get('Id') for row in fresh)
            for row in fresh:
                if parse(row):
                    e = parse(row, get(c, urljoin(SOURCE['url'], row['Url'])).text)
                    events[e.url] = e
            if not fresh or page * 50 + len(data['value']) >= data.get('@odata.count', float('inf')):
                break
        else:
            warn_limit(__name__)
    return list(events.values())
