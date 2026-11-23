"""IndeHub: discover yearly hackathon pages from the public event archive."""
import re
import time

from ._organizer_util import HTMLParser, body, client, check_robots, fetch, schema
from ._platforms_util import absolute

SOURCE = {"id": "indehub", "name": "IndeHub", "url": "https://indehub.org/events",
          "method": "api", "default_kind": "hackathon"}


def parse(html):
    events = schema(html, SOURCE, location='Bengaluru, India', country='IN')
    text = body(html)
    prize = re.search(r'Total announced prize pool:\s*([^A-Za-z]+)', text)
    for e in events:
        if prize:
            e.prize = prize[1].strip()
            # The announced pool includes hardware; never label it all cash.
            e.signals['prize_noncash'] = True
    return events


def collect():
    from ._vertical_util import MAX_PAGES, warn_limit
    events = {}
    with client() as c:
        check_robots(c, SOURCE['url'])
        time.sleep(1.1)
        html = fetch(c, SOURCE['url']).text
        urls = {absolute(a.attributes['href'], SOURCE['url']) for a in HTMLParser(html).css('a[href]')
                if re.fullmatch(r'/hackathon/20\d{2}/?', a.attributes['href'])}
        if len(urls) > MAX_PAGES:
            warn_limit(__name__)
        for n, url in enumerate(sorted(urls)):
            if n >= MAX_PAGES:
                break
            for e in parse(fetch(c, url).text):
                events[e.url] = e
    return list(events.values())
