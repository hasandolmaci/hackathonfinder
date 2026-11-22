"""MLH's public Inertia JSON listing; no HTML requests or browser required."""
from datetime import datetime, timezone
from urllib.parse import urljoin
from hackfinder.models import Event
from ._mlh_taikai_util import client, check_robots, json_response, date, upcoming

SOURCE = dict(id='mlh', name='Major League Hacking', url='https://www.mlh.com/seasons/2027/events', method='api', default_kind='hackathon')

def collect() -> list[Event]:
    # A season runs Aug-Jul and is named for the year it ends in: read the
    # current and the next ones. A season that does not exist yet is a 404.
    year = datetime.now(timezone.utc).year
    rows, seen = [], set()
    with client() as c:
        check_robots(c, SOURCE['url'])
        headers = {'X-Inertia': 'true', 'Accept': 'application/json'}
        for season in (year, year + 1, year + 2):
            url = SOURCE['url'].replace('/2027/', f'/{season}/')
            r = c.get(url, headers=headers)
            # Inertia tells clients the current deployment version in its 409 response.
            if r.status_code == 409 and r.headers.get('x-inertia-version'):
                headers['X-Inertia-Version'] = r.headers['x-inertia-version']
                r = c.get(url, headers=headers)
            if r.status_code == 404:
                continue
            props = json_response(r)['props']
            if 'upcomingEvents' not in props:
                raise RuntimeError('MLH listing schema changed: missing upcomingEvents')
            rows += [row for row in props['upcomingEvents'] if row['id'] not in seen and not seen.add(row['id'])]
    result = []
    for row in rows:
        start, end = date(row.get('startsAt')), date(row.get('endsAt'))
        if not upcoming(start, end):
            continue
        fmt = {'physical':'in-person', 'digital':'online', 'virtual':'online', 'online':'online', 'hybrid':'hybrid'}.get(row.get('formatType'), 'unknown')
        custom = row.get('customFields') or {}
        tags = ['student'] + [str(t).lower() for t in custom.get('hackathon_focus', [])]
        if any('High School' in t for t in custom.get('underserved_types', [])):
            tags.append('high-school')
        result.append(Event(source='mlh', source_id=row['id'], title=row['name'].strip(),
            url=urljoin(SOURCE['url'], row.get('websiteUrl') or row['url']), start=start, end=end,
            format=fmt, location=row.get('location') if fmt != 'online' else None,
            country=(row.get('venueAddress') or {}).get('country'), image=row.get('backgroundUrl'),
            organizer=row.get('organizationName'), tags=tags, signals={'mlh_member': True}, kind='hackathon', confidence=0.9, classified_by='source'))
    return result
