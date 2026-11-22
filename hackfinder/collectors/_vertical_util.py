"""Private helpers for lablab, Kaggle, itch.io, Luma and Meetup."""
from __future__ import annotations

import json
import logging
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser

UA = "Hackfinder/1.0 (public upcoming event discovery)"
MAX_PAGES = 100  # Safety limit per listing or scope.
_last_hit: dict[str, float] = {}


def warn_limit(name, what="listing"):
    logging.getLogger(name).warning("hit the %d-page safety limit for %s; results may be incomplete", MAX_PAGES, what)


def client(timeout=12):
    return httpx.Client(timeout=timeout, follow_redirects=True,
                        headers={"User-Agent": UA, "Accept": "application/json"})


def robots(c, url):
    """Merge matching robots groups, including repeated wildcard groups."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    cache = getattr(c, "_hf_robots", {})
    response = cache.get(origin)
    if response is None:
        response = c.get(origin + "/robots.txt", timeout=6)
        cache[origin] = response
        c._hf_robots = cache
    if response.status_code in (404, 410):
        return
    if response.status_code in (401, 403, 429):
        raise RuntimeError(f"blocked: robots.txt HTTP {response.status_code} at {parts.netloc}")
    response.raise_for_status()
    groups, agents, rules = [], [], []
    for line in response.text.splitlines() + ["User-agent: __end__"]:
        line = line.split("#", 1)[0].strip()
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.lower().strip(), value.strip()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key in ("allow", "disallow") and agents and value:
            rules.append((key, value))
    matches = [(max((len(a) for a in aa if a != "*" and a in UA.lower()), default=0), rr)
               for aa, rr in groups if "*" in aa or any(a in UA.lower() for a in aa)]
    specificity = max((x[0] for x in matches), default=-1)
    target = parts.path + ("?" + parts.query if parts.query else "")
    applicable = []
    for rank, rr in matches:
        if rank != specificity:
            continue
        for kind, pattern in rr:
            expression = re.escape(pattern).replace(r"\*", ".*")
            if pattern.endswith("$"):
                expression = expression[:-2] + "$"
            if re.match(expression, target):
                applicable.append((len(pattern.replace("*", "").rstrip("$")), kind == "allow"))
    if applicable and not max(applicable)[1]:
        raise RuntimeError(f"blocked: robots.txt disallows {url}")


def get_json(c, url, **kwargs):
    r = c.get(url, **kwargs)
    if r.status_code in (401, 403, 429):
        raise RuntimeError(f"blocked: HTTP {r.status_code} from {url}")
    r.raise_for_status()
    if "json" not in r.headers.get("content-type", ""):
        raise RuntimeError(f"blocked: expected public JSON from {url}")
    return r.json()


def polite_json(c, url, *, gap=1.2, retries=3, **kwargs):
    """get_json with per-host spacing (gap plus jitter) and backoff on 429/5xx,
    honoring Retry-After. 401/403 and a persistent 429 raise as blocked."""
    host = urlsplit(url).netloc
    for attempt in range(retries + 1):
        pause = _last_hit.get(host, 0) + gap + random.uniform(0, 0.4) - time.monotonic()
        if pause > 0:
            time.sleep(pause)
        r = c.get(url, **kwargs)
        _last_hit[host] = time.monotonic()
        if r.status_code not in (429, 500, 502, 503, 504) or attempt == retries:
            break
        try:
            wait = float(r.headers.get("retry-after", ""))
        except ValueError:
            wait = 5 * 2 ** attempt
        time.sleep(min(wait, 60))
    if r.status_code in (401, 403, 429):
        raise RuntimeError(f"blocked: HTTP {r.status_code} from {url}")
    r.raise_for_status()
    if "json" not in r.headers.get("content-type", ""):
        raise RuntimeError(f"blocked: expected public JSON from {url}")
    return r.json()


def dt(value):
    if value is None or value == "":
        return None
    try:
        if isinstance(value, dict):
            value = value.get("seconds") or value.get("value")
        if isinstance(value, (float, int)):
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc)
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def upcoming(start, end):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (end or start) is None or (end or start) >= today


def plain(value):
    return " ".join(HTMLParser(str(value or "")).text().split())[:500] or None


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def embedded(page):
    tree = HTMLParser(page.content())
    for node in tree.css('script[type="application/ld+json"], script[type="application/json"], script#__NEXT_DATA__'):
        try:
            yield from walk(json.loads(node.text()))
        except (ValueError, TypeError):
            continue


def script_objects(page):
    """Read JSON literals embedded in JS bootstrap calls, without executing JS."""
    decoder = json.JSONDecoder()
    for script in HTMLParser(page.content()).css("script:not([src])"):
        text = script.text()
        pos = 0
        while pos < len(text):
            found = re.search(r"[\[{]", text[pos:])
            if not found:
                break
            pos += found.start()
            try:
                value, size = decoder.raw_decode(text[pos:])
            except ValueError:
                pos += 1
                continue
            yield from walk(value)
            pos += size


def check_block(page):
    text = page.locator("body").inner_text(timeout=5000)[:12000].lower()
    if any(s in text for s in ("verify you are human", "checking your browser", "access denied",
                                "just a moment...", "unusual traffic", "complete the captcha")):
        raise RuntimeError(f"blocked: challenge or access denial at {page.url}")
    if page.locator('iframe[src*="captcha"]').count():
        # Kaggle embeds invisible enterprise reCAPTCHA on normal public pages;
        # a visible challenge is the point at which collection must stop.
        if any(x.is_visible() for x in page.locator('iframe[src*="captcha"]').all()):
            raise RuntimeError(f"blocked: CAPTCHA at {page.url}")
    return text


def navigate(page, url, selector):
    response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
    if response and response.status in (401, 403, 429):
        raise RuntimeError(f"blocked: HTTP {response.status} at {url}")
    if response and response.status >= 400:
        raise RuntimeError(f"HTTP {response.status} at {url}")
    page.wait_for_selector("body", timeout=8000)
    check_block(page)
    try:
        page.wait_for_selector(selector, timeout=12000)
    except Exception:
        check_block(page)
        raise


def browser_worker(module):
    """Bound browser startup too: cdp_page may otherwise hang before yielding."""
    from hackfinder.browser import _sem

    script = ("import importlib,json; "
              f"m=importlib.import_module('hackfinder.collectors.{module}'); "
              "events=m._collect(); "
              "print('HF_EVENTS_JSON='+json.dumps([e.model_dump(mode='json') for e in events]))")
    # Reserve a slot in the pipeline process as well as the isolated worker's
    # cdp_page semaphore, so isolation does not increase global concurrency.
    if not _sem.acquire(timeout=100):
        raise RuntimeError("browser unavailable: no browser slot within 100 seconds")
    try:
        try:
            result = subprocess.run([sys.executable, "-c", script], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=600)
        except subprocess.TimeoutExpired:
            raise RuntimeError("browser unavailable: cdp_page did not finish within 600 seconds") from None
    finally:
        _sem.release()
    if result.returncode:
        error = result.stderr.strip().splitlines()
        raise RuntimeError(error[-1] if error else "browser worker failed")
    from hackfinder.models import Event
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("HF_EVENTS_JSON="):
            return [Event.model_validate(x) for x in json.loads(line.partition("=")[2])]
    raise RuntimeError("browser worker returned no result")


def schema_event(raw, source, base, kind, tags=()):
    from hackfinder.models import Event
    typ = raw.get("@type", "")
    if not any("Event" in str(t) for t in (typ if isinstance(typ, list) else [typ])):
        return None
    title, url = raw.get("name"), raw.get("url")
    if not title or not url or "EventCancelled" in str(raw.get("eventStatus", "")):
        return None
    start, end = dt(raw.get("startDate")), dt(raw.get("endDate"))
    if not upcoming(start, end):
        return None
    location = raw.get("location") or {}
    locations = location if isinstance(location, list) else [location]
    online = "OnlineEventAttendanceMode" in str(raw.get("eventAttendanceMode", ""))
    hybrid = "MixedEventAttendanceMode" in str(raw.get("eventAttendanceMode", ""))
    physical, address, country = None, {}, None
    for loc in locations:
        if isinstance(loc, str):
            physical = loc
        elif loc.get("@type") == "VirtualLocation":
            online = True
        else:
            address = loc.get("address") or {}
            if isinstance(address, dict):
                country = address.get("addressCountry")
                if isinstance(country, dict):
                    country = country.get("name")
                physical = ", ".join(str(x) for x in [address.get("addressLocality"), country] if x) or loc.get("name")
            else:
                physical = str(address) or loc.get("name")
    organizer = raw.get("organizer") or {}
    if isinstance(organizer, list):
        organizer = organizer[0] if organizer else {}
    image = raw.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    return Event(source=source, url=urljoin(base, url), title=title,
                 description=plain(raw.get("description")), start=start, end=end,
                 image=urljoin(base, image) if image else None,
                 format="hybrid" if hybrid or (online and physical) else "online" if online else "in-person" if physical else "unknown",
                 location=physical, country=country,
                 organizer=organizer.get("name") if isinstance(organizer, dict) else str(organizer),
                 tags=list(tags), kind=kind, confidence=0.9 if kind != "unknown" else 0,
                 classified_by="source" if kind != "unknown" else "none")
