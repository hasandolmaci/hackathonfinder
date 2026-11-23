"""make.fun: unauthenticated public competitions API and cursor pagination."""
from ._organizer_util import client, check_robots, fetch, make
from ._platforms_util import MAX_PAGES, current, utc, warn_limit
from ._signals_util import count, money

SOURCE = {"id": "makefun", "name": "make.fun", "url": "https://make.fun/",
          "method": "api", "default_kind": "mixed"}
API = 'https://make.fun/api/competitions'


def parse(rows):
    events = []
    for r in rows:
        if r.get('status') not in ('open', 'upcoming') or r.get('demo') or r.get('houseOnly'):
            continue
        end = utc(r.get('deadline'))
        if not end or not current(None, end):
            continue
        amount = r.get('rewardAmount')
        sponsor = r.get('sponsor') or {}
        # submissionCount counts attempts, not unique builders.
        evidence = money(amount, 'USDC') | {'entries': count(r.get('submissionCount'))}
        if sponsor.get('name'):
            evidence['sponsors'] = [sponsor['name']]
        if r.get('skills'):
            evidence['themes'] = r['skills']
        if r.get('entryFeeUsd') is not None:
            evidence['paid_entry'] = float(r['entryFeeUsd']) > 0
        e = make(SOURCE, r.get('title'), r.get('url') or f"/bounty/{r['slug']}", r.get('publishedAt'), end,
            source_id=r.get('id'), text=r.get('description') or r.get('summary'), deadline=end,
            organizer=sponsor.get('name') or 'make.fun', fmt='online', prize=f'{amount} USDC' if amount is not None else None,
            evidence={k:v for k,v in evidence.items() if v is not None}, kind='unknown')
        if e:
            events.append(e)
    return events


def collect():
    import time
    events, seen, cursors, cursor = {}, set(), set(), None
    with client() as c:
        check_robots(c, SOURCE['url'])
        time.sleep(1.1)
        for _ in range(MAX_PAGES):
            data = fetch(c, API, params={'cursor': cursor} if cursor else {}).json()
            rows = data.get('items')
            if not isinstance(rows, list):
                raise RuntimeError('make.fun no longer returns items')
            fresh = [r for r in rows if r['id'] not in seen]
            seen.update(r['id'] for r in fresh)
            events.update({e.url: e for e in parse(fresh)})
            cursor = data.get('next_cursor')
            if not fresh or not cursor or cursor in cursors:
                break
            cursors.add(cursor)
        else:
            warn_limit(__name__)
    return list(events.values())
