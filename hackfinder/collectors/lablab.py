"""lablab.ai/ai-hackathons redirects to Starfield Labs' public AI hackathon listing (one page)."""
from urllib.parse import urljoin
from hackfinder.browser import cdp_page
from hackfinder.models import Event
from ._html_util import HTMLParser, objects, current, load
from ._vertical_util import browser_worker, client, robots, schema_event, dt, plain

SOURCE = dict(id='lablab', name='lablab.ai', url='https://lablab.ai/ai-hackathons', method='scrape', default_kind='hackathon')
LISTING = 'https://starfieldlabs.ai/ai-hackathons'


def parse(html: str, base_url: str) -> list[Event]:
    events = {}
    for raw in objects(html):
        event = schema_event(raw, 'lablab', base_url, 'hackathon', ['ai'])
        # Also support bootstrap event records when cards hydrate on the client.
        if event is None and raw.get('slug') and (raw.get('title') or raw.get('name')):
            start = dt(raw.get('startDate') or raw.get('startAt') or raw.get('startsAt'))
            end = dt(raw.get('endDate') or raw.get('endAt') or raw.get('endsAt'))
            if start or end:
                event = Event(source='lablab', title=raw.get('title') or raw['name'],
                    url=urljoin(base_url, '/ai-hackathons/' + raw['slug']), start=start, end=end,
                    description=plain(raw.get('description')), format='online' if raw.get('isOnline') else 'unknown',
                    tags=['ai'], kind='hackathon', confidence=0.9, classified_by='source')
        if event and current(event.start, event.end):
            events[event.url] = event
    tree = HTMLParser(html)
    for link in tree.css('main a[href*="/ai-hackathons/"]'):
        heading = link.css_first('h2,h3,h4')
        times = link.css('time[datetime]')
        if heading is None or not times:
            continue
        start = dt(times[0].attributes['datetime'])
        end = dt(times[-1].attributes['datetime']) if len(times) > 1 else None
        url = urljoin(base_url, link.attributes['href'])
        if current(start, end) and url not in events:
            events[url] = Event(source='lablab', title=heading.text(strip=True), url=url,
                start=start, end=end, tags=['ai'], kind='hackathon', confidence=0.9, classified_by='source')
    if not events and not tree.css('main a[href*="/ai-hackathons/"]') and 'no events yet' not in tree.text().lower():
        raise RuntimeError('Starfield listing has no recognized events or explicit empty state')
    return list(events.values())


def collect() -> list[Event]:
    with client() as c:
        robots(c, LISTING)
    return browser_worker('lablab')


def _collect() -> list[Event]:
    with cdp_page() as page:
        load(page, LISTING, 'main')
        return parse(page.content(), page.url)
