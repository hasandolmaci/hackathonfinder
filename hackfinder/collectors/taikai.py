"""TAIKAI public GraphQL discovery API (documented in its API catalog)."""
import re
from urllib.parse import quote
from hackfinder.models import Event
from ._mlh_taikai_util import MAX_PAGES, client, check_robots, json_response, date, upcoming, plain, warn_limit

SOURCE = dict(id='taikai', name='TAIKAI', url='https://taikai.network/en/hackathons', method='api', default_kind='hackathon')
ENDPOINT = 'https://api.taikai.network/api/graphql'
QUERY = '''query Discovery($page:Int) { challenges(page:$page) {
 id name slug shortDescription prize prizeCurrency{name} participantsCount
 organization{name slug} coverImageFile{url} tags{title} steps{name startDate}
} }'''

def collect() -> list[Event]:
    result, seen = [], set()
    with client() as c:
        check_robots(c, ENDPOINT)
        # Old editions can coexist with future ones, so do not stop at the first
        # expired row: page until the API runs dry (about 15 pages of 20).
        for page in range(MAX_PAGES):
            payload = json_response(c.post(ENDPOINT, json={'query': QUERY, 'variables': {'page': page}}))
            if payload.get('errors'):
                raise RuntimeError('TAIKAI GraphQL: ' + '; '.join(e['message'] for e in payload['errors']))
            rows = payload['data']['challenges']
            if not rows or all(r['id'] in seen for r in rows):
                break
            for row in rows:
                if row['id'] in seen:
                    continue
                seen.add(row['id'])
                steps = sorted([(date(s['startDate']), s['name'].strip()) for s in row.get('steps', []) if s.get('startDate')])
                end = steps[-1][0] if steps else None
                build = [d for d, n in steps if re.search(r'hackathon.*start|hackathon kick|hacking starts|project development|developing|building starts|^hackathon$|^hacking$|event days|desenvolvimento|início do hackathon', n, re.I)]
                start = min(build) if build else None
                if not upcoming(start, end):
                    continue
                deadlines = [d for d,n in steps if re.search(r'registration.*(deadline|closes)', n, re.I)]
                org = row['organization']
                currency = (row.get('prizeCurrency') or {}).get('name')
                amount = row.get('prize')
                result.append(Event(source='taikai', source_id=row['id'], title=row['name'].strip(),
                    url=f"https://taikai.network/en/{quote(org['slug'])}/hackathons/{quote(row['slug'])}",
                    description=plain(row.get('shortDescription')), start=start, end=end,
                    registration_deadline=min(deadlines) if deadlines else None,
                    image=(row.get('coverImageFile') or {}).get('url'), organizer=org['name'],
                    prize=f'{amount:,.0f} {currency}' if amount and currency else None,
                    prize_usd=float(amount) if amount and currency == 'USD' else None,
                    participants=row.get('participantsCount'), tags=[t['title'].lower() for t in row.get('tags', [])],
                    kind='hackathon', confidence=0.9, classified_by='source'))
        else:
            warn_limit(__name__)
    return result
