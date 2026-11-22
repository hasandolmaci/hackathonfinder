"""ETHGlobal hackathons from the listing's embedded event records."""
from urllib.parse import urljoin
from hackfinder.browser import cdp_page
from hackfinder.models import Event
from ._html_util import objects, current, load
from ._vertical_util import browser_worker, client, robots, dt

SOURCE = dict(id='ethglobal', name='ETHGlobal', url='https://ethglobal.com/events', method='scrape', default_kind='hackathon')


def parse(html: str, base_url: str) -> list[Event]:
    events = {}
    for raw in objects(html):
        if raw.get('type') != 'hackathon' or not raw.get('slug') or not raw.get('name'):
            continue
        start, end = dt(raw.get('startTime')), dt(raw.get('endTime'))
        if not (start or end) or not current(start, end) or raw.get('status') in ('cancelled', 'canceled'):
            continue
        online = raw.get('medium') in ('virtual', 'online', 'async')
        city = raw.get('city') or {}
        country = (city.get('country') or {}).get('name')
        location = ', '.join(x for x in [city.get('name'), country] if x) or None
        url = urljoin(base_url, '/events/' + raw['slug'])
        banner = raw.get('banner') or {}
        events[url] = Event(source='ethglobal', source_id=str(raw['id']) if raw.get('id') else raw['slug'],
            title=raw['name'], url=url, start=start, end=end,
            registration_deadline=dt(raw.get('signupDeadline')),
            format='online' if online else 'hybrid' if raw.get('medium') == 'hybrid' else 'in-person',
            location=None if online else location, country=None if online else country,
            image=urljoin(base_url, banner['fullUrl']) if banner.get('fullUrl') else None,
            description=raw.get('tagline'), organizer='ETHGlobal', tags=['web3'],
            kind='hackathon', confidence=0.9, classified_by='source')
    return list(events.values())


def collect() -> list[Event]:
    with client() as c:
        robots(c, SOURCE['url'])
    return browser_worker('ethglobal')


def _collect() -> list[Event]:
    with cdp_page() as page:
        load(page, SOURCE['url'], 'a[href*="/events/"]')
        return parse(page.content(), page.url)
