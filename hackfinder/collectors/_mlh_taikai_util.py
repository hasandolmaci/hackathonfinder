"""Private helpers for MLH, TAIKAI, HackerEarth, ETHGlobal and Hackathon.com."""
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser
import json
import logging
import re
import subprocess
import sys
import tempfile

UA = 'Hackfinder/1.0 (public upcoming hackathon discovery)'
MAX_PAGES = 100  # Safety limit per listing or scope.

def warn_limit(name, what='listing'):
    logging.getLogger(name).warning('hit the %d-page safety limit for %s; results may be incomplete', MAX_PAGES, what)

def client():
    return httpx.Client(timeout=12, follow_redirects=True, headers={'User-Agent': UA})

def check_robots(c, url):
    origin = '{0.scheme}://{0.netloc}'.format(urlsplit(url))
    r = c.get(origin + '/robots.txt')
    if r.status_code in (401, 403, 429):
        raise RuntimeError(f'blocked: robots.txt returned HTTP {r.status_code} at {origin}')
    if r.status_code == 404:
        return
    r.raise_for_status()
    if 'text/html' in r.headers.get('content-type', ''):
        raise RuntimeError(f'blocked: unexpected HTML robots response at {origin}')
    rules = RobotFileParser()
    rules.parse(r.text.splitlines())
    if not rules.can_fetch(UA, url):
        raise RuntimeError(f'blocked: robots.txt disallows {url}')

def json_response(r):
    if r.status_code in (401, 403, 429):
        raise RuntimeError(f'blocked: HTTP {r.status_code} at {r.url}')
    r.raise_for_status()
    if 'json' not in r.headers.get('content-type', ''):
        raise RuntimeError(f'Expected public JSON at {r.url}')
    return r.json()

def date(value):
    if not value:
        return None
    d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return d.replace(tzinfo=d.tzinfo or timezone.utc).astimezone(timezone.utc)

def upcoming(start, end):
    return (end or start) is None or (end or start).date() >= datetime.now(timezone.utc).date()

def plain(value):
    return ' '.join(HTMLParser(str(value or '')).text().split())[:500] or None

def check_page(page):
    text = page.locator('body').inner_text().lower()
    if any(x in text for x in ('verify you are human', 'checking your browser', 'sorry, you have been blocked', 'access denied', 'complete the captcha')):
        raise RuntimeError('blocked: site presented an access challenge')

def navigate(page, url, selector):
    r = page.goto(url, wait_until='domcontentloaded', timeout=15000)
    if r and r.status in (401, 403, 429):
        raise RuntimeError(f'blocked: HTTP {r.status} at {url}')
    if r and r.status >= 400:
        raise RuntimeError(f'HTTP {r.status} at {url}')
    page.wait_for_selector('body', timeout=5000)
    check_page(page)
    try:
        page.wait_for_selector(selector, timeout=8000)
    except Exception:
        check_page(page)
        raise

def browser_worker(module):
    """Bound the whole cdp_page worker run."""
    from hackfinder.browser import _sem
    if not _sem.acquire(timeout=100):
        raise RuntimeError('browser unavailable: no browser slot within 100 seconds')
    try:
        code = (f'import json; from hackfinder.collectors.{module} import _collect; '
                'print("HF_RESULT="+json.dumps([e.model_dump(mode="json") for e in _collect()]))')
        # Files avoid a Chrome descendant keeping inherited pipe handles open
        # after the Python worker times out on Windows.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                r = subprocess.run([sys.executable, '-c', code], stdout=out, stderr=err, timeout=600)
            except subprocess.TimeoutExpired:
                raise RuntimeError('browser unavailable: cdp_page worker exceeded 600 seconds') from None
            out.seek(0)
            err.seek(0)
            stdout = out.read().decode('utf-8', errors='replace')
            stderr = err.read().decode('utf-8', errors='replace')
        if r.returncode:
            lines = stderr.strip().splitlines()
            raise RuntimeError(lines[-1] if lines else 'browser worker failed')
        from hackfinder.models import Event
        for line in reversed(stdout.splitlines()):
            if line.startswith('HF_RESULT='):
                return [Event.model_validate(e) for e in json.loads(line[len('HF_RESULT='):])]
        raise RuntimeError('browser worker returned no result')
    finally:
        _sem.release()

def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)

def schema_events(html):
    tree = HTMLParser(html)
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            payload = json.loads(node.text())
        except ValueError:
            continue
        for row in walk_json(payload):
            if 'Event' in str(row.get('@type', '')) and row.get('name'):
                yield row

def written_date(text):
    """Date-only fallback: printed times without timezone are not UTC evidence."""
    text = re.sub(r'(\d)(st|nd|rd|th)\b', r'\1', text)
    for fmt in ('%d %B %Y', '%B %d %Y', '%b %d %Y'):
        try:
            return datetime.strptime(text.strip().replace(',', ''), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    raise ValueError(f'Unrecognized event date: {text}')
