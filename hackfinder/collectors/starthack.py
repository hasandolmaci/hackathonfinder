"""START Global's current site plus START Berlin's calendar and START Munich event cards."""
import json
import re
from urllib.parse import urljoin

from hackfinder.models import Event
from ._ecosystem_util import HACK, HTMLParser, MAX_PAGES, client, dates, get, parse_schema, robots, text_tree, upcoming, warn_limit
from ._signals_util import signals
from ._vertical_util import polite_json

SOURCE = {'id': 'starthack', 'name': 'START Hack', 'url': 'https://www.startglobal.org/start-hack',
          'method': 'api', 'default_kind': 'hackathon'}
BERLIN = 'cal-bl55Ki232KTKkOd'  # Embedded by start-berlin.com, no login.
MUNICH = 'https://www.startmunich.de/events'


def parse(html, url=SOURCE['url']):
    events = parse_schema(html, 'starthack', url, 'hackathon')
    for e in events:
        e.url = 'https://starthack.eu/#/register'
    return events


def munich(html):
    result = []
    tree = HTMLParser(html)
    for a in tree.css('a[data-ph-event="event_card_clicked"]'):
        props = json.loads(a.attributes.get('data-ph-props') or '{}')
        title = props.get('event_title') or ''
        if not HACK.search(title):
            continue
        text = a.text(separator=' ', strip=True)
        # Munich cards use Nov 21, 2026.
        m = re.search(r'([A-Za-z]+)\s+(\d{1,2}),\s*(20\d{2})', text)
        start, end = dates(f'{m[2]} {m[1]} {m[3]}') if m else (None, None)
        if not start or not upcoming(start, end):
            continue
        result.append(Event(source='starthack', source_id=a.attributes['href'], title=title,
            url=urljoin(MUNICH, a.attributes['href']), start=start, end=end,
            location='Munich, Germany', country='Germany', format='in-person', organizer='START Munich',
            kind='hackathon', confidence=0.9, classified_by='source', signals=signals(text=text)))
    return result


def tours(html):
    result = []
    tree = HTMLParser(html)
    for card in tree.css('.framer-hack-events-list__card-content'):
        title = card.css_first('h3')
        info = card.css('.framer-hack-events-list__info-item')
        link = card.css_first('a[href]')
        if not title or not info or not link:
            continue
        start, end = dates(info[0].text())
        if not start or not upcoming(start, end):
            continue
        place = info[1].text(strip=True) if len(info) > 1 else None
        text = card.text(separator=' ', strip=True)
        cash = re.search(r"([\d][\d' ]*)\s*CHF\s*(?:Prize|cash)", text, re.I) or re.search(r"CHF\s*([\d][\d' ]*)\s*(?:Prize|cash)", text, re.I)
        amount = float(re.sub(r"[' ]", '', cash[1])) if cash else None
        result.append(Event(source='starthack', source_id=title.text(strip=True), title=title.text(strip=True),
            url=urljoin(SOURCE['url'], link.attributes['href']), start=start, end=end, format='in-person',
            location=place, country=place.rsplit(',', 1)[-1].strip() if place and ',' in place else None,
            organizer='START Global', prize=f'{amount:g} CHF' if amount else None,
            kind='hackathon', confidence=0.9, classified_by='source',
            signals=signals(text=text, **({'prize_amount': amount, 'prize_currency': 'CHF'} if amount else {}))))
    return result


def collect():
    result = {}
    with client(timeout=20) as c:
        robots(c, SOURCE['url'])
        events = parse(get(c, SOURCE['url']).text)
        result.update({e.url: e for e in events})
        result.update({e.url: e for e in tours(get(c, SOURCE['url'] + '/events').text)})
        robots(c, MUNICH)
        result.update({e.url: e for e in munich(get(c, MUNICH).text)})
        cursor, seen = None, set()
        from .luma import _event
        for _ in range(MAX_PAGES):
            data = polite_json(c, 'https://api.lu.ma/calendar/get-items', params={
                'calendar_api_id': BERLIN, 'period': 'future', 'pagination_limit': 50,
                **({'pagination_cursor': cursor} if cursor else {})})
            rows = data.get('entries')
            if not isinstance(rows, list):
                raise RuntimeError('START Berlin: Luma calendar entries missing')
            fresh = [r for r in rows if (r.get('event') or {}).get('api_id') not in seen]
            seen.update((r.get('event') or {}).get('api_id') for r in fresh)
            for row in fresh:
                raw = row.get('event') or {}
                if not HACK.search(raw.get('name', '')):
                    continue
                e = _event(row)
                if e:
                    e.source, e.organizer = 'starthack', 'START Berlin'
                    # Berlin calendar includes talks, so keep classification unknown.
                    result[e.url] = e
            cursor = data.get('next_cursor')
            if not fresh or not data.get('has_more') or not cursor:
                break
        else:
            warn_limit(__name__, 'START Berlin')
    return list(result.values())
