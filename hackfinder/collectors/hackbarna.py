"""HackBarna: event archive + public Next flight edition records."""
import re
import time

from ._organizer_util import HTMLParser, client, check_robots, fetch, make, objects
from ._platforms_util import MAX_PAGES, absolute, warn_limit
from ._signals_util import names

SOURCE = {"id": "hackbarna", "name": "HackBarna", "url": "https://www.hackbarna.com/en/events",
          "method": "api", "default_kind": "hackathon"}


def parse(html):
    events = {}
    for r in objects(html):
        if not r.get('slug') or not r.get('startDate') or r.get('eventType') != 'hackathon':
            continue
        desc = r.get('description') or {}
        desc = desc.get('en') if isinstance(desc, dict) else desc
        prize = r.get('prizes') or {}
        prize = prize.get('en', []) if isinstance(prize, dict) else []
        perks = [p for row in prize if isinstance(row, dict) for p in row.get('perks', [])]
        challenges = r.get('challenges') or {}
        themes = [c['title'] for c in challenges.get('en', []) if c.get('title')] if isinstance(challenges, dict) else []
        e = make(SOURCE, r.get('name'), r.get('registrationUrl') or f"/en/events/{r['slug']}",
            r.get('startDate'), r.get('endDate'), source_id=r.get('id'), text=desc,
            location=r.get('location') or 'Barcelona, Spain', country='ES', fmt='in-person',
            image=r.get('imageUrl'), prize='; '.join(perks)[:500] or None,
            evidence={'sponsors': names(r.get('sponsors')), **({'themes': themes} if themes else {}),
                      **({'prize_noncash': True} if perks else {})})
        if e:
            events[e.url] = e
    return list(events.values())


def collect():
    events = {}
    with client() as c:
        check_robots(c, SOURCE['url'])
        time.sleep(1.1)
        html = fetch(c, SOURCE['url']).text
        urls = {absolute(a.attributes['href'], SOURCE['url']) for a in HTMLParser(html).css('a[href]')
                if re.fullmatch(r'/en/events/[^/#]+', a.attributes['href'])}
        for n, url in enumerate(sorted(urls)):
            if n >= MAX_PAGES:
                warn_limit(__name__)
                break
            for e in parse(fetch(c, url).text):
                events[e.url] = e
    return list(events.values())
