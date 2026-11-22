"""Private normalization and polite public-JSON access for platform collectors."""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urljoin, urlsplit

import httpx

UA = "Hackfinder/1.0 (public upcoming hackathon discovery)"
MAX_PAGES = 100  # Safety limit per listing or scope.


def warn_limit(name: str, what: str = "listing") -> None:
    logging.getLogger(name).warning("hit the %d-page safety limit for %s; results may be incomplete", MAX_PAGES, what)


def client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"},
                        timeout=12, follow_redirects=True)


def check_robots(c: httpx.Client, url: str) -> float:
    """Honor wildcard rules, including Allow specificity (needed by Unstop)."""
    parts = urlsplit(url)
    r = c.get(f"{parts.scheme}://{parts.netloc}/robots.txt")
    if r.status_code in (404, 410):
        return 0
    if r.status_code in (401, 403, 429):
        raise RuntimeError(f"blocked: robots.txt returned HTTP {r.status_code} for {parts.netloc}")
    r.raise_for_status()
    if "<html" in r.text[:500].lower():
        raise RuntimeError(f"blocked: robots.txt did not return rules for {parts.netloc}")
    groups, agents, rules = [], [], []
    for raw in r.text.splitlines() + ["User-agent: __end__"]:
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        if key.lower() == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif agents and key.lower() in ("allow", "disallow", "crawl-delay"):
            rules.append((key.lower(), value))
    specific = [g for g in groups if any(a != "*" and a in UA.lower() for a in g[0])]
    selected = specific or [g for g in groups if "*" in g[0]]
    matches, delay = [], 0.0
    path = parts.path + ("?" + parts.query if parts.query else "")
    for _, group_rules in selected:
        for key, value in group_rules:
            if key == "crawl-delay":
                try:
                    delay = max(delay, float(value))
                except ValueError:
                    pass
            elif value:
                pattern = re.escape(value).replace(r"\*", ".*")
                pattern = pattern[:-2] + "$" if value.endswith("$") else pattern
                if re.match(pattern, path):
                    matches.append((len(value.replace("*", "").rstrip("$")), key == "allow"))
    if matches and not max(matches)[1]:
        raise RuntimeError(f"blocked: robots.txt disallows {url}")
    if delay:
        time.sleep(min(delay, 20))
    return delay


def json_response(r: httpx.Response):
    if r.status_code in (401, 403, 429):
        raise RuntimeError(f"blocked: HTTP {r.status_code} from {r.url}")
    r.raise_for_status()
    if "json" not in r.headers.get("content-type", "").lower():
        text = r.text[:1500].lower()
        if any(s in text for s in ("captcha", "access denied", "just a moment", "cloudflare")):
            raise RuntimeError(f"blocked: challenge page from {r.url}")
        raise RuntimeError(f"Expected public JSON from {r.url}; endpoint may have changed")
    return r.json()


def utc(value) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def current(start, end, *, date_only=False) -> bool:
    now = datetime.now(timezone.utc)
    if end is not None and not date_only:
        return end >= now
    # Date-only values are midnight UTC; retain events throughout their last day.
    last = end or start
    return last is None or last.date() >= now.date()


def plain(value, limit=500) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", str(value)))).strip()[:limit] or None


def absolute(value, base) -> str | None:
    if not value:
        return None
    url = urljoin(base, str(value).strip())
    return url if urlsplit(url).scheme in ("http", "https") and urlsplit(url).netloc else None


def number(value) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return None
