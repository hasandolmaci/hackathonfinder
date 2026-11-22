"""Hackathon.com listing cards and Marko bootstrap records."""
import re
from datetime import datetime, timezone
from urllib.parse import urljoin
from hackfinder.browser import cdp_page
from hackfinder.models import Event
from ._html_util import HTMLParser, objects, current, load
from ._vertical_util import MAX_PAGES, browser_worker, client, robots, dt, plain, warn_limit

SOURCE = dict(id='hackathoncom', name='Hackathon.com', url='https://www.hackathon.com', method='scrape', default_kind='mixed')


def _range(text, year):
    months = r'(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?'
    match = re.search(months + r'\s+(\d{1,2})\s*[–—-]\s*(?:' + months + r'\s+)?(\d{1,2})(?:,?\s+(20\d{2}))?', text, re.I)
    if not match:
        return None, None
    m1, d1, m2, d2, y = match.groups()
    year = int(y or year)
    month1 = datetime.strptime(m1[:3].title(), '%b').month
    month2 = datetime.strptime((m2 or m1)[:3].title(), '%b').month
    return (datetime(year, month1, int(d1), tzinfo=timezone.utc),
            datetime(year + (month2 < month1), month2, int(d2), tzinfo=timezone.utc))


def _make(title, url, start, end, location=None, description=None, organizer=None, tags=(), image=None):
    if not current(start, end):
        return None
    online = bool(location and re.search(r'online|virtual', location, re.I))
    # Aggregator categories also contain workshops. Only the title supplies a hint.
    hack = bool(re.search(r'\bhack(?:athon|fest|day|s)\b', title, re.I))
    prizes = re.findall(r'\$[\d,]+(?:\.\d+)?[^.!?]{0,45}?\b(?:in prizes(?: overall)?|prize pool|grand prize)\b', description or '', re.I)
    prize = next((p for p in prizes if 'overall' in p.lower()), prizes[0] if prizes else None)
    amount = re.search(r'\$([\d,.]+)', prize or '')
    return Event(source='hackathoncom', source_id=url.rstrip('/').rsplit('-', 1)[-1], title=title,
        url=url, start=start, end=end, format='online' if online else 'in-person' if location else 'unknown',
        location=None if online else location, description=plain(description), organizer=organizer,
        tags=list(tags), image=image, prize=prize, prize_usd=float(amount[1].replace(',', '')) if amount else None,
        kind='hackathon' if hack else 'unknown', confidence=0.9 if hack else 0,
        classified_by='source' if hack else 'none')


def parse(html: str, base_url: str) -> list[Event]:
    events = {}
    for raw in objects(html):
        if not raw.get('slug') or not raw.get('name') or 'date_start' not in raw:
            continue
        if raw.get('deleted'):
            continue
        location = 'Online' if raw.get('online') else ', '.join(x for x in [raw.get('city'), raw.get('country')] if isinstance(x, str) and x) or raw.get('venue')
        event = _make(raw['name'], urljoin(base_url, '/event/' + raw['slug']),
            dt(raw.get('date_start')), dt(raw.get('date_end')), location,
            plain(raw.get('desc')), raw.get('organizerName'), raw.get('topic') or [])
        if event:
            events[event.url] = event
    tree = HTMLParser(html)
    for card in tree.css('.ht-event-card'):
        link = card.css_first('.ht-event-card__title')
        if link is None:
            continue
        url = urljoin(base_url, link.attributes['href'])
        if url in events:
            continue
        desc = card.css_first('.ht-event-card__desc')
        description = desc.text(separator=' ', strip=True) if desc else ''
        year_match = re.search(r'\b20\d{2}\b', description)
        year = int(year_match[0]) if year_match else datetime.now(timezone.utc).year
        start, end = _range(description, year)
        date_node = card.css_first('.ht-event-card__date')
        if start is None and date_node:
            match = re.search(r'(\d{1,2})\s+([A-Za-z]{3})(?:\s+(20\d{2}))?', date_node.text())
            if match:
                start = datetime.strptime(f'{match[1]} {match[2]} {match[3] or year}', '%d %b %Y').replace(tzinfo=timezone.utc)
        loc = card.css_first('.ht-event-card__location')
        event = _make(link.text(strip=True), url, start, end,
            loc.text(strip=True) if loc else None, description,
            tags=[n.text(strip=True) for n in card.css('.ht-event-topics__tag')])
        if event:
            events[url] = event
    return list(events.values())


def collect() -> list[Event]:
    return browser_worker('hackathoncom')


def _listing(c, page, url, events):
    """Read one listing, following ?page=N until it is exhausted: the "N out of M"
    total is reached, or a page adds nothing new (the site repeats the last page)."""
    for n in range(1, MAX_PAGES + 1):
        paged = url if n == 1 else f'{url}?page={n}'
        robots(c, paged)
        load(page, paged, 'body')
        page.wait_for_timeout(1500)
        html = page.content()
        fresh = [e for e in parse(html, page.url) if e.url not in events]
        events.update((e.url, e) for e in fresh)
        total = re.search(r'(\d+)\s+out of\s+(\d+)', HTMLParser(html).text())
        if not fresh or (total and int(total[1]) >= int(total[2])):
            return
    warn_limit(__name__, url)


def _collect() -> list[Event]:
    events = {}
    # Home is the global upcoming list and /online a subset; each theme page lists
    # upcoming events too, which catches any that home does not show.
    with client() as c, cdp_page() as page:
        for url in (SOURCE['url'], SOURCE['url'] + '/online'):
            _listing(c, page, url, events)
        load(page, SOURCE['url'] + '/theme', 'a[href^="/theme/"]')
        themes = page.locator('a[href^="/theme/"]').evaluate_all('els => [...new Set(els.map(e => e.getAttribute("href")))]')
        for href in themes:
            _listing(c, page, SOURCE['url'] + href, events)
    return list(events.values())
