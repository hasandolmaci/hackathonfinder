"""Public organizer HTML, JSON-LD and Next flight data (no JavaScript execution)."""
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from hackfinder.models import Event
from ._platforms_util import absolute, check_robots, client, current, plain, utc
from ._signals_util import count, geo, money, names, noncash, reward, signals
from ._vertical_util import schema_event, walk

_hits = {}


def fetch(c, url, **kwargs):
    host = urlsplit(url).netloc
    pause = _hits.get(host, 0) + 1.1 - time.monotonic()
    if pause > 0:
        time.sleep(pause)
    r = c.get(url, **kwargs)
    _hits[host] = time.monotonic()
    if r.status_code in (401, 403, 429):
        raise RuntimeError(f"blocked: HTTP {r.status_code} from {url}")
    r.raise_for_status()
    if any(x in r.text[:2000].lower() for x in ('<title>just a moment', 'verify you are human')):
        raise RuntimeError(f"blocked: challenge at {url}")
    return r


def objects(html):
    """JSON-LD and decoded flight objects, including objects inside flight row strings."""
    decoder = json.JSONDecoder()
    def scan(text):
        pos = 0
        while pos < len(text):
            m = re.search(r'[\[{]', text[pos:])
            if not m:
                break
            pos += m.start()
            try:
                value, size = decoder.raw_decode(text[pos:])
            except ValueError:
                pos += 1
                continue
            yield from walk(value)
            if isinstance(value, list) and len(value) == 2 and value[0] == 1 and isinstance(value[1], str):
                yield from scan(value[1])
            pos += size
    for script in HTMLParser(html).css('script:not([src])'):
        yield from scan(script.text())


def body(html):
    tree = HTMLParser(html)
    for n in tree.css('script, style, svg, nav, footer'):
        n.decompose()
    return ' '.join(tree.text(separator=' ').split())


def registration(html, base):
    for a in HTMLParser(html).css('a[href]'):
        label, href = a.text().strip(), a.attributes['href']
        if re.search(r'register|apply(?: now| as a hacker)?$|enroll|join the hackathon|报名', label, re.I):
            if re.search(r'judge|mentor|volunteer|sponsor|discord|account|host|sign in|/portal', label + ' ' + href, re.I):
                continue
            if href.startswith('#') or '/auth' in href or '/login' in href:
                continue
            if url := absolute(href, base):
                return url
    return None


def make(source, title, url, start, end=None, *, text=None, location=None, country=None,
         fmt='unknown', organizer=None, prize=None, participants=None, evidence=None, image=None,
         deadline=None, kind='hackathon', source_id=None):
    start, end = utc(start), utc(end)
    if not title or not absolute(url, source['url']) or not (start or end) or not current(start, end, date_only=True):
        return None
    cash = reward(prize) if prize and not noncash(prize) else {}
    evidence = signals(text=text, registrations=count(participants), **cash) | (evidence or {})
    return Event(source=source['id'], source_id=str(source_id) if source_id is not None else None,
        title=plain(title), url=absolute(url, source['url']), start=start, end=end,
        description=plain(text), image=absolute(image, source['url']), registration_deadline=utc(deadline),
        format=fmt, location=location, country=country, organizer=organizer or source['name'],
        prize=prize, prize_usd=evidence.get('prize_amount') if evidence.get('prize_currency') == 'USD' else None,
        participants=count(participants), signals=evidence, kind=kind,
        confidence=0.9 if kind != 'unknown' else 0, classified_by='source' if kind != 'unknown' else 'none')


def schema(html, source, *, location=None, country=None):
    result = {}
    rows = list(objects(html))
    refs = {r['@id']: r for r in rows if r.get('@id') and r.get('name')}
    parents = {id(r['superEvent']) for r in rows if isinstance(r.get('superEvent'), dict)}
    for raw in rows:
        if id(raw) in parents:
            continue
        if 'Event' not in str(raw.get('@type', '')) or not (raw.get('startDate') or raw.get('endDate')):
            continue
        if 'Cancelled' in str(raw.get('eventStatus', '')):
            continue
        row = dict(raw)
        row.setdefault('url', source['url'])
        org = row.get('organizer') or {}
        if isinstance(org, dict) and org.get('@id') in refs:
            row['organizer'] = refs[org['@id']]
        e = schema_event(row, source['id'], source['url'], 'hackathon')
        if not e:
            continue
        loc = row.get('location') or {}
        loc = loc[0] if isinstance(loc, list) and loc else loc
        loc = loc if isinstance(loc, dict) else {}
        coords = loc.get('geo') or {}
        text = body(html)
        e.url = registration(html, source['url']) or e.url
        e.organizer = e.organizer or source['name']
        e.location = e.location or location or loc.get('name')
        e.country = e.country or country
        if e.format == 'unknown' and e.location:
            e.format = 'in-person'
        if e.format == 'online':
            e.location = e.country = None
        e.signals = signals(text=text, sponsors=names(row.get('sponsor')) if isinstance(row.get('sponsor'), list) else None,
            themes=[s.strip() for s in row['keywords'].split(',')] if isinstance(row.get('keywords'), str) else None,
            **geo(coords.get('latitude'), coords.get('longitude')))
        result[e.url] = e
    return list(result.values())


MONTHS = {m: i for i, m in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), 1)}


def dates(text):
    """Explicit English date/range with year; never infer an edition from copyright."""
    text = re.sub(r'(\d)(?:st|nd|rd|th)\b', r'\1', text)
    m = re.search(r'\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})\s*(?:[–—+\-]\s*(?:[A-Za-z]+\s+)?(\d{1,2}))?\s*,?\s*(20\d{2})\b', text, re.I)
    if not m:
        m = re.search(r'\b(\d{1,2})\s*(?:[–—\-]\s*(\d{1,2}))?\s+([A-Za-z]{3})[a-z]*\s+(20\d{2})\b', text, re.I)
        parts = (m[3], m[1], m[2], m[4]) if m else None
    else:
        parts = m[1], m[2], m[3], m[4]
    if not parts or parts[0].lower() not in MONTHS:
        return None, None
    month, day, last, year = parts
    try:
        return (datetime(int(year), MONTHS[month.lower()], int(day), tzinfo=timezone.utc),
                datetime(int(year), MONTHS[month.lower()], int(last or day), tzinfo=timezone.utc))
    except ValueError:
        return None, None


def collect_page(source, parse):
    with client() as c:
        check_robots(c, source['url'])
        time.sleep(1.1)
        return parse(fetch(c, source['url']).text)
