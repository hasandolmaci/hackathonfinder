"""HackUK: event index + server-rendered event details; exclude talks."""
import re
import time

from ._organizer_util import HTMLParser, body, client, check_robots, dates, fetch, make, registration
from ._platforms_util import MAX_PAGES, absolute, warn_limit

SOURCE = {"id": "hackuk", "name": "HackUK", "url": "https://www.hackuk.network/events",
          "method": "api", "default_kind": "mixed"}


def parse(html, url):
    tree, text = HTMLParser(html), body(html)
    title = tree.css_first('h1')
    if not title or not re.search(r'hack|game.?jam|counterspell|campfire', title.text(), re.I):
        return []
    start, end = dates(text)
    loc = re.search(r'Location\s+(.+?)\s+Participants', text)
    participants = re.search(r'Participants\s+(\d+)', text)
    # The details page labels this Participants, without an actual registered count.
    evidence = {'capacity': int(participants[1])} if participants else {}
    e = make(SOURCE, title.text(), registration(html, url) or url, start, end, text=text,
        location=loc[1] if loc else None, country='GB' if loc else None, fmt='in-person' if loc else 'unknown',
        evidence=evidence, kind='unknown')
    return [e] if e else []


def collect():
    events = {}
    with client() as c:
        check_robots(c, SOURCE['url'])
        time.sleep(1.1)
        html = fetch(c, SOURCE['url']).text
        urls = {absolute(a.attributes['href'], SOURCE['url']) for a in HTMLParser(html).css('a[href]')
                if re.fullmatch(r'/events/[^/#]+', a.attributes['href'])}
        for n, url in enumerate(sorted(urls)):
            if n >= MAX_PAGES:
                warn_limit(__name__)
                break
            for e in parse(fetch(c, url).text, url):
                events[e.url] = e
    return list(events.values())
