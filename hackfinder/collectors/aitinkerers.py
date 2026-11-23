"""AI Tinkerers' upcoming directory; More requires a browser on the current edge."""
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from ._html_util import objects
from ._platforms_util import absolute, current
from ._signals_util import geo, signals
from ._vertical_util import MAX_PAGES, browser_worker, check_block, client, robots, schema_event, warn_limit

SOURCE = {"id": "aitinkerers", "name": "AI Tinkerers", "url": "https://aitinkerers.org/events",
          "method": "scrape", "default_kind": "mixed"}


def parse(html, base=SOURCE["url"]):
    events = {}
    for r in objects(html):
        e = schema_event(r, "aitinkerers", base, "unknown", ["ai"])
        if not e or not (e.start or e.end) or not current(e.start, e.end):
            continue
        loc = r.get("location") or {}
        coords = (loc.get("geo") or {}) if isinstance(loc, dict) else {}
        e.signals = signals(text=r.get("description"), **geo(coords.get("latitude"), coords.get("longitude")))
        events[e.url] = e
    return list(events.values())


def links(html):
    return list(dict.fromkeys(u for n in HTMLParser(html).css('a.event-card-title-link')
                             if (u := absolute(n.attributes.get("href"), SOURCE["url"]))))


def collect():
    return browser_worker("aitinkerers")


def _collect():
    from hackfinder.browser import cdp_page
    events, seen, urls = {}, set(), []
    with client(timeout=20) as c:
        robots(c, SOURCE["url"])
    with cdp_page() as page:
        page.goto(SOURCE["url"], wait_until="domcontentloaded", timeout=20000)
        check_block(page)
        page.wait_for_selector("#events-list", timeout=12000)
        for _ in range(MAX_PAGES):
            html = page.content()
            for e in parse(html):
                events[e.url] = e
            fresh = [u for u in links(html) if u not in seen]
            seen.update(fresh)
            urls.extend(fresh)
            more = page.locator("button.load-more-events")
            if not fresh or not more.count():
                break
            before = len(links(html))
            page.wait_for_timeout(1200)
            more.first.evaluate('b => b.click()')  # the cookie banner overlays the button; consent stays unanswered
            page.wait_for_function("n => new Set([...document.querySelectorAll('a.event-card-title-link')].map(a=>a.href)).size > n || !document.querySelector('button.load-more-events')", arg=before, timeout=20000)
            check_block(page)
        else:
            warn_limit(__name__)
        # Appended cards do not add JSON-LD; their original public pages do.
        for url in urls:
            if url in events:
                continue
            page.wait_for_timeout(1200)
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            check_block(page)
            for e in parse(page.content(), url):
                events[e.url] = e
    return list(events.values())
