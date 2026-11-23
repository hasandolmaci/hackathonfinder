"""StartupAmsterdam business calendar, full HTML pagination and Event JSON-LD."""
from ._ecosystem_util import listing, parse_schema, text_tree
from ._signals_util import signals

SOURCE = {'id': 'startupamsterdam', 'name': 'StartupAmsterdam', 'url': 'https://www.iamsterdam.com/en/business/calendar',
          'method': 'api', 'default_kind': 'mixed'}


def parse(html, url):
    events = parse_schema(html, 'startupamsterdam', url)
    tree = text_tree(html)
    for e in events:
        text = tree.text(separator=' ', strip=True)
        at = text.find(e.title)
        e.signals.update(signals(text=text[at:] if at >= 0 else text))
        e.description = e.signals.get('text', '')[:500] or e.description
        if 'AI Builders is a community organizing' in text:
            e.organizer = 'AI Builders'
    return events


def collect():
    return listing(SOURCE, 'a[href*="/business/calendar/events/"]', parse)
