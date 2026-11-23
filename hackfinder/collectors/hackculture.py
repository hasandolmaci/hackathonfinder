"""HackCulture: public hackathon/program JSON, paginated with skip/limit."""
import time

from ._organizer_util import client, check_robots, fetch, make
from ._platforms_util import MAX_PAGES, utc, warn_limit
from ._signals_util import geo, money, names, count

SOURCE = {"id": "hackculture", "name": "HackCulture", "url": "https://hackculture.io/programs",
          "method": "api", "default_kind": "mixed"}
API = 'https://api.hackculture.io/api/v1/hackathons/'


def parse(rows):
    events = []
    for r in rows:
        if r.get('type') not in ('hackathon', 'innovation_challenge') or r.get('is_completed') or r.get('status') != 'published':
            continue
        loc = r.get('location') or {}
        loc = loc if isinstance(loc, dict) else {'name': loc}
        coords = loc.get('coordinates') or []
        evidence = geo(coords[1], coords[0]) if len(coords) == 2 else {}
        prizes, totals = r.get('prizes') or [], {}
        for p in prizes:
            if p.get('type') == 'cash' and p.get('currency') and (cash := money(p.get('value'), p['currency'])):
                unit = cash['prize_currency']
                totals[unit] = totals.get(unit, 0) + cash['prize_amount']
        if len(totals) == 1:
            unit = next(iter(totals))
            evidence.update(money(totals[unit], unit))
        if prizes:
            evidence['prize_noncash'] = any(p.get('type') not in ('cash', None) for p in prizes)
        if r.get('themes'):
            evidence['themes'] = names(r['themes'])
        sponsors = list(dict.fromkeys([*names([p for p in r.get('partners') or [] if p.get('type') == 'sponsor']),
                                      *[p['sponsor'] for p in prizes if p.get('sponsor')]]))
        if sponsors:
            evidence['sponsors'] = sponsors
        prize = '; '.join(f"{p.get('value') or ''} {p.get('currency') or ''} {p.get('name') or ''}".strip() for p in prizes) or None
        e = make(SOURCE, r.get('name'), r.get('external_registration_url') or f"https://hackculture.io/hackathons/{r.get('slug') or r['_id']}",
            r.get('start_datetime'), r.get('end_datetime'), source_id=r.get('_id'), text=r.get('about') or r.get('description') or r.get('tagline'),
            fmt={'offline': 'in-person', 'online': 'online', 'hybrid': 'hybrid'}.get(r.get('mode'), 'unknown'),
            location=loc.get('address') or loc.get('name'), country=loc.get('country') or ('IN' if 'India' in (loc.get('address') or '') else None),
            organizer=r.get('organizer_name'), participants=r.get('total_participants'),
            image=(r.get('branding') or {}).get('cover_photo'), evidence=evidence, prize=prize, kind='unknown')
        if e:
            deadlines = [utc(p.get('end_datetime')) for p in r.get('phases') or [] if p.get('type') == 'registration']
            e.registration_deadline = max((d for d in deadlines if d), default=None)
            if e.format == 'online':
                e.location = e.country = None
            events.append(e)
    return events


def collect():
    events, seen = {}, set()
    with client() as c:
        check_robots(c, SOURCE['url'])
        time.sleep(1.1)
        for page in range(MAX_PAGES):
            rows = fetch(c, API, params={'skip': page * 50, 'limit': 50}).json()
            if not isinstance(rows, list):
                raise RuntimeError('HackCulture no longer returns a program array')
            fresh = [r for r in rows if r['_id'] not in seen]
            seen.update(r['_id'] for r in fresh)
            live = {e.source_id for e in parse(fresh)}
            for r in fresh:
                if r['_id'] in live:
                    detail = fetch(c, 'https://api.hackculture.io/api/v1/hackathon', params={'id': r['_id']}).json()
                    if not isinstance(detail, dict) or not detail.get('_id'):
                        raise RuntimeError('HackCulture detail no longer returns a program')
                    events.update({e.url: e for e in parse([r | detail])})
            if not fresh or len(rows) < 50:
                break
        else:
            warn_limit(__name__)
    return list(events.values())
