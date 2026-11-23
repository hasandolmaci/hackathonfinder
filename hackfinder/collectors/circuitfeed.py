"""CircuitFeed: public Supabase catalog/read RPCs used by the official event UI."""
from ._organizer_util import client, check_robots, fetch, make
from ._platforms_util import MAX_PAGES, current, utc, warn_limit
from ._signals_util import names, noncash

SOURCE = {"id": "circuitfeed", "name": "CircuitFeed", "url": "https://www.circuitfeed.tech/hackathons",
          "method": "api", "default_kind": "mixed"}
API = 'https://tpbmbxndqavjmexjljqg.supabase.co/rest/v1/rpc/'
# Public publishable key shipped in the website; no user session or private key.
HEADERS = {'apikey': 'sb_publishable_N4ddLwO66nkU3RDAB4ALWg_R2PgAMwj'}


def parse(data):
    r = data.get('event') or {}
    if r.get('status') != 'published':
        return []
    prizes = data.get('prizes') or []
    prize = '; '.join(p.get('description') or p.get('title') or '' for p in prizes)
    prize = '; '.join(dict.fromkeys(prize.split('; '))) or None
    participants = data.get('registrations_count', r.get('registrations_count'))
    evidence = {'sponsors': names(data.get('sponsors')), 'themes': names(data.get('tracks'))}
    if noncash(prize):
        evidence['prize_noncash'] = True
    e = make(SOURCE, r.get('title'), f"https://www.circuitfeed.tech/hackathon/{r.get('slug')}",
        r.get('submissions_open_at') or r.get('registration_opens_at'), r.get('submissions_close_at'),
        deadline=r.get('registration_closes_at'), text=(r.get('description_md') or '') + '\n' + (r.get('rules_md') or ''),
        source_id=r.get('id'), fmt='online', participants=participants, image=r.get('poster_url'),
        prize=prize[:500] if prize else None, evidence=evidence, kind='unknown')
    return [e] if e else []


def collect():
    import time
    events = {}
    with client() as c:
        check_robots(c, SOURCE['url'])
        time.sleep(1.1)
        rows = fetch(c, API + 'hackathon_catalog', headers=HEADERS).json()
        if not isinstance(rows, list):
            raise RuntimeError('CircuitFeed no longer returns a catalog array')
        for n, r in enumerate(rows):
            if n >= MAX_PAGES:
                warn_limit(__name__)
                break
            if r.get('status') != 'published' or not current(utc(r.get('submissions_open_at')), utc(r.get('submissions_close_at'))):
                continue
            data = fetch(c, API + 'hackathon_read', params={'p_slug': r['slug']}, headers=HEADERS).json()
            events.update({e.url:e for e in parse(data)})
    return list(events.values())
