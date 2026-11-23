"""HackRice: the current edition's server-rendered landing page."""
from ._organizer_util import HTMLParser, body, collect_page, dates, make, registration, schema

SOURCE = {"id": "hackrice", "name": "HackRice", "url": "https://hackrice.com/",
          "method": "api", "default_kind": "hackathon"}


def parse(html):
    if events := schema(html, SOURCE, location='Rice University, Houston, United States', country='US'):
        return events
    text = body(html)
    start, end = dates(text)
    tree = HTMLParser(html)
    title = tree.css_first('title')
    sponsors = [n.attributes['aria-label'].split(' — ')[0] for n in tree.css('#sponsors a[aria-label]')]
    themes = list(dict.fromkeys(n.text().strip() for n in tree.css('#tracks h3')))
    evidence = {k:v for k,v in {'sponsors': sponsors, 'themes': themes}.items() if v}
    # "500+ builders" is promotional capacity, not a registration count.
    e = make(SOURCE, title.text().split('|')[0].strip() if title else 'HackRice',
        registration(html, SOURCE['url']) or SOURCE['url'], start, end, text=text,
        location='Rice University, Houston, Texas, United States', country='US', fmt='in-person',
        organizer='Rice University', evidence=evidence)
    return [e] if e else []


def collect():
    return collect_page(SOURCE, parse)
