"""SheNicest: public platform event JSON; only dated hackathons, no volunteer calls."""
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ._organizer_util import client, check_robots, fetch, make
from ._signals_util import count

SOURCE = {"id": "shenicest", "name": "SheNicest", "url": "https://shenicest.com/platform/events",
          "method": "api", "default_kind": "mixed"}
API = 'https://shenicest.com/platform/api/events/list.php?include_closed=1'


def stamp(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value)
        return d.replace(tzinfo=d.tzinfo or ZoneInfo('Asia/Shanghai')).astimezone(timezone.utc)
    except ValueError:
        return None


def parse(data):
    if not data.get('success') or not isinstance(data.get('events'), list):
        raise RuntimeError('SheNicest no longer returns events')
    events = []
    for r in data['events']:
        if r.get('status') != 'published' or not re.search(r'hackathon|黑客松', r.get('title', ''), re.I):
            continue
        loc = r.get('location')
        online = bool(loc and ('线上' in loc or 'online' in loc.lower()))
        evidence = {'capacity': count(r['capacity'])} if r.get('capacity') is not None else {}
        e = make(SOURCE, r.get('title'), r.get('registration_url') or f"/platform/events/{r['id']}",
            stamp(r.get('start_time')), stamp(r.get('end_time')), deadline=stamp(r.get('deadline')),
            text=(r.get('description') or '') + ' ' + (r.get('content_html') or ''), source_id=r['id'],
            location=None if online else loc, country=None if online else 'CN',
            fmt='online' if online else 'in-person' if loc else 'unknown', evidence=evidence, kind='unknown')
        if e:
            events.append(e)
    return events


def collect():
    import time
    with client() as c:
        check_robots(c, SOURCE['url'])
        time.sleep(1.1)
        return parse(fetch(c, API).json())
