"""Public HTML helpers for the organizer/calendar collectors (no JavaScript execution)."""
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ._platforms_util import current, plain
from ._signals_util import count, geo, names, reward, signals
from ._vertical_util import MAX_PAGES, client, dt, robots, schema_event, upcoming, walk, warn_limit

HACK = re.compile(r"hack|hakaton|buildathon|datathon|ideathon|\bctf\b|capture.the.flag|programming contest|programmeerwedstrijd|programmeercompetitie|programmierwettbewerb|game[ -]?jam|\bnwerc\b", re.I)
NOISE = re.compile(r"life.?hack|growth.?hack|powerpoint.?hack", re.I)
MONTHS = {m: i for i, mm in enumerate(('jan january januari januar', 'feb february februari februar',
    'mar march maart märz', 'apr april', 'may mei mai', 'jun june juni', 'jul july juli',
    'aug august augustus', 'sep sept september', 'oct october oktober okt', 'nov november',
    'dec december dez dezember'), 1) for m in mm.split()}
_hits = {}


def get(c, url, **kwargs):
    host = urlsplit(url).netloc
    for attempt in range(4):
        time.sleep(max(0, _hits.get(host, 0) + 1.1 - time.monotonic()))
        r = c.get(url, headers={"Accept": "text/html,application/json,application/xml"}, **kwargs)
        _hits[host] = time.monotonic()
        if r.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
            break
        try:
            delay = float(r.headers.get('retry-after', ''))
        except ValueError:
            delay = 2 ** (attempt + 1)
        time.sleep(min(delay, 60))
    if r.status_code in (401, 403, 429):
        raise RuntimeError(f"blocked: HTTP {r.status_code} from {url}")
    r.raise_for_status()
    if re.search(r'verify you are human|just a moment\.\.\.|checking your browser', r.text, re.I):
        raise RuntimeError(f"blocked: challenge at {url}")
    return r


def text_tree(html):
    tree = HTMLParser(html)
    for node in tree.css('script,style,nav,footer,header,#cookie-wrapper,[data-nosnippet]'):
        node.decompose()
    return tree


def dates(text):
    """Explicit year required; local dates at midnight in Central European time."""
    pattern = r'(\d{1,2})\.?\s*(?:[-–]|to|bis|t/m)?\s*(\d{1,2})?\.?\s*([A-Za-zäÄ]+)\.?\s+(20\d{2})'
    result = []
    for m in re.finditer(pattern, text or '', re.I):
        month = MONTHS.get(m[3].lower())
        if not month:
            continue
        try:
            for day in (m[1], m[2]) if m[2] else (m[1],):
                result.append(datetime(int(m[4]), month, int(day), tzinfo=ZoneInfo('Europe/Berlin')).astimezone(timezone.utc))
        except ValueError:
            continue
    return (result[0], result[-1]) if result else (None, None)


def registration(tree, base):
    for a in tree.css('a[href]'):
        href = urljoin(base, a.attributes['href'])
        if urlsplit(href).scheme not in ('http', 'https'):
            continue
        if re.search(r'luma\.com/|lu\.ma/|pretix\.eu/|forms\.office\.com/', href) and re.search(r'apply|register|anmeld|bewerb|sign.up|hier|visit website', a.text(), re.I):
            return href
    return None


def parse_schema(html, source, base, kind='unknown'):
    tree, result = HTMLParser(html), []
    for script in tree.css('script[type="application/ld+json"]'):
        try:
            nodes = walk(json.loads(script.text()))
        except ValueError:
            continue
        for raw in nodes:
            title = raw.get('name') or ''
            if not HACK.search(title + ' ' + str(raw.get('description') or '')) or NOISE.search(title):
                continue
            raw = dict(raw, url=raw.get('url') or base)
            e = schema_event(raw, source, base, kind)
            if not e or not (e.start or e.end):
                continue
            if not current(e.start, e.end, date_only=len(str(raw.get('endDate') or raw.get('startDate') or '')) == 10):
                continue
            offers = raw.get('offers') or []
            offers = [offers] if isinstance(offers, dict) else offers
            link = next((o.get('url') for o in offers if isinstance(o, dict) and o.get('url')), None)
            e.url = urljoin(base, link or registration(tree, base) or e.url)
            e.source_id = str(raw.get('@id') or base)
            loc = raw.get('location') or {}
            loc = loc[0] if isinstance(loc, list) and loc else loc
            coordinate = loc.get('geo') or {} if isinstance(loc, dict) else {}
            award = raw.get('award') or raw.get('prize')
            award = ' '.join(map(str, award)) if isinstance(award, list) else award
            e.prize = plain(award) if award else None
            e.participants = count(raw.get('attendeeCount'))
            org = raw.get('organizer') or []
            if isinstance(org, list):
                e.organizer = ', '.join(names(org)) or e.organizer
            e.signals = signals(text=raw.get('description'), registrations=e.participants,
                sponsors=names(raw['sponsor'] if isinstance(raw['sponsor'], list) else [raw['sponsor']]) if raw.get('sponsor') else None,
                themes=[x.strip() for x in raw['keywords'].split(',')] if isinstance(raw.get('keywords'), str) else raw.get('keywords'),
                **reward(award), **geo(coordinate.get('latitude'), coordinate.get('longitude')))
            result.append(e)
    return result


def listing(source, selector, parser=None):
    """Exhaust HTML pagination; visit only keyword-matched event links."""
    result, visited, seen, fingerprints = {}, set(), set(), set()
    queue = [source['url']]
    with client(timeout=20) as c:
        robots(c, source['url'])
        for _ in range(MAX_PAGES):
            if not queue:
                break
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            html = get(c, url).text
            tree = HTMLParser(html)
            if not tree.css(selector):
                raise RuntimeError(f"{source['id']}: listing structure missing at {url}")
            fingerprint = tuple(a.attributes.get('href') for a in tree.css(selector))
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            for a in tree.css(selector):
                href = urljoin(url, a.attributes.get('href', '')).split('#')[0]
                title = plain(a.text(), 3000) or ''
                if href in seen or not HACK.search(title) or NOISE.search(title):
                    continue
                seen.add(href)
                detail = get(c, href).text
                events = parser(detail, href) if parser else parse_schema(detail, source['id'], href)
                result.update({e.url: e for e in events})
            for a in tree.css('a[rel="next"], .pagination a[href], a[aria-label*="Next"], .paginationContainer a[href], [aria-label="Pagination"] a[href]'):
                href = urljoin(url, a.attributes.get('href', ''))
                if href not in visited and href not in queue:
                    queue.append(href)
        else:
            if queue:
                warn_limit(source['id'])
    return list(result.values())
