"""Loops House: complete embedded Builder Arena records + live event JSON-LD."""
import time

from ._organizer_util import client, check_robots, fetch, objects, schema
from ._platforms_util import MAX_PAGES, current, utc, warn_limit
from ._signals_util import count, money

SOURCE = {"id": "loops", "name": "Loops House", "url": "https://www.loops.house/builder-arena",
          "method": "api", "default_kind": "hackathon"}


def listings(html):
    return {r['slug']: r for r in objects(html) if r.get('slug') and r.get('startDate')
            and r.get('published') is True and r.get('eventType') == 'hackathon'
            and current(utc(r.get('startDate')), utc(r.get('endDate')))}


def parse(html):
    events = schema(html, SOURCE)
    meta = next((r for r in objects(html) if 'registeredCount' in r and 'prizePool' in r), {})
    for e in events:
        e.participants = count(meta.get('registeredCount'))
        e.registration_deadline = utc(meta.get('registrationDeadline'))
        if e.participants is not None:
            e.signals['registrations'] = e.participants
        e.signals.update(money(meta.get('prizePool'), meta.get('currency')))
        if meta.get('prizePool'):
            e.prize = f"{meta['prizePool']:,.0f} {meta.get('currency') or ''}".strip()
            if meta.get('currency') == 'USD':
                e.prize_usd = float(meta['prizePool'])
    return events


def collect():
    events = {}
    with client() as c:
        check_robots(c, SOURCE['url'])
        time.sleep(1.1)
        rows = listings(fetch(c, SOURCE['url']).text)
        for n, slug in enumerate(rows):
            if n >= MAX_PAGES:
                warn_limit(__name__)
                break
            for e in parse(fetch(c, f'https://www.loops.house/{slug}').text):
                events[e.url] = e
    return list(events.values())
