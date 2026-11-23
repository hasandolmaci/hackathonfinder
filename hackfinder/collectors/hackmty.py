"""HackMTY: public Vite bundle's English event copy, without running JavaScript."""
import re

from ._organizer_util import HTMLParser, client, check_robots, dates, fetch, make
from ._platforms_util import absolute
from ._signals_util import geo

SOURCE = {"id": "hackmty", "name": "HackMTY", "url": "https://hackmty.com/",
          "method": "api", "default_kind": "hackathon"}


def parse(bundle):
    date = re.search(r'"location\.card\.whenValue"\s*,\s*"([^"]+)"', bundle)
    start, end = dates(date[1]) if date else (None, None)
    url = re.search(r'href:\s*"(https://experience\.hackmty\.com[^" ]*)"', bundle)
    e = make(SOURCE, f'HackMTY {start.year}' if start else 'HackMTY', url[1] if url else SOURCE['url'],
        start, end, text='36 hour long Hackathon at Tec de Monterrey, Monterrey NL.',
        location='Arena Borregos, Tecnológico de Monterrey, Monterrey, Mexico', country='MX',
        fmt='in-person', organizer='Tec ACM')
    # Coordinates must be read from the source, not supplied from a geocoder.
    coords = re.search(r'(\d+\.\d+)° N\s*/\s*(\d+\.\d+)° W', bundle)
    if e and coords:
        e.signals.update(geo(coords[1], -float(coords[2])))
    return [e] if e else []


def collect():
    import time
    with client() as c:
        check_robots(c, SOURCE['url'])
        time.sleep(1.1)
        html = fetch(c, SOURCE['url']).text
        script = HTMLParser(html).css_first('script[type="module"][src]')
        if not script:
            raise RuntimeError('HackMTY module script missing')
        return parse(fetch(c, absolute(script.attributes['src'], SOURCE['url'])).text)
