"""YES!Delft upcoming event cards; general calendar, strict keyword pre-filter."""
from hackfinder.models import Event
from ._ecosystem_util import HACK, dates, listing, parse_schema, text_tree, upcoming
from ._platforms_util import plain
from ._signals_util import signals

SOURCE = {'id': 'yesdelft', 'name': 'YES!Delft', 'url': 'https://yesdelft.com/events/',
          'method': 'api', 'default_kind': 'mixed'}


def parse(html, url):
    structured = parse_schema(html, 'yesdelft', url)
    if structured:
        return structured
    tree = text_tree(html)
    h = tree.css_first('h1')
    if not h or not HACK.search(h.text()):
        return []
    def value(n):  # the <dd> after a <dt>, skipping whitespace text nodes
        x = n.next
        while x is not None and x.tag == '-text':
            x = x.next
        return x
    fields = {n.text(strip=True): value(n).text(strip=True) for n in tree.css('.event-info-box dt') if value(n) is not None}
    start, _ = dates(fields.get('Start date'))
    end, _ = dates(fields.get('End date'))
    if not start:
        return []  # undated listing: skip rather than fail the whole source
    if not upcoming(start, end):
        return []
    place = fields.get('Where')
    if place == 'Location not set':
        place = None
    link = next((a.attributes['href'] for a in tree.css('a[href]') if a.text(strip=True) == 'Website'), url)
    return [Event(source='yesdelft', source_id=url, url=link, title=plain(h.text()), start=start, end=end,
        registration_deadline=dates(fields.get('Final registration date'))[0],
        format='online' if place and 'online' in place.lower() else 'in-person' if place else 'unknown',
        location=place, organizer='YES!Delft', description=plain(tree.text()), signals=signals(text=tree.text()))]


def collect():
    return listing(SOURCE, 'a[href*="yesdelft.com/events/"]', parse)
