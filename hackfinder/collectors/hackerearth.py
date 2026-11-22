"""Public feed used by HackerEarth's browser extension."""
from urllib.parse import urljoin, urlsplit
from hackfinder.models import Event
from ._mlh_taikai_util import client, check_robots, json_response, date, upcoming, plain

SOURCE = dict(id='hackerearth', name='HackerEarth', url='https://www.hackerearth.com/challenges/hackathon/', method='api', default_kind='mixed')
ENDPOINT = 'https://www.hackerearth.com/chrome-extension/events/'

def collect() -> list[Event]:
    with client() as c:
        check_robots(c, ENDPOINT)
        rows = json_response(c.get(ENDPOINT))['response']
    result = []
    for row in rows:
        start, end = date(row.get('start_utc_tz') or row.get('start_tz')), date(row.get('end_utc_tz') or row.get('end_tz'))
        if not upcoming(start, end) or row.get('status') not in ('ONGOING', 'UPCOMING'):
            continue
        url = urljoin(SOURCE['url'], row['url'])
        kind = 'hackathon' if '/hackathon/' in urlsplit(url).path else 'coding_competition'
        result.append(Event(source='hackerearth', source_id=urlsplit(url).path.rstrip('/').split('/')[-1],
            title=row['title'], url=url, description=plain(row.get('description')), start=start, end=end,
            image=row.get('cover_image') or row.get('thumbnail'), kind=kind, confidence=0.9, classified_by='source'))
    return result
