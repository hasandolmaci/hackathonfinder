"""Official API when configured; otherwise parse the public rendered listing."""
import os
import re
from urllib.parse import urljoin

from hackfinder.browser import cdp_page
from hackfinder.models import Event
from ._signals_util import source_signals
from ._vertical_util import MAX_PAGES, browser_worker, client, dt, plain, robots, warn_limit
from ._html_util import current


_AUTH = bool(os.getenv("KAGGLE_USERNAME") and os.getenv("KAGGLE_KEY"))
SOURCE = {"id": "kaggle", "name": "Kaggle", "url": "https://www.kaggle.com/competitions",
          "method": "api" if _AUTH else "scrape", "default_kind": "coding_competition"}
API = "https://www.kaggle.com/api/v1/competitions/list"
ACTIVE = "https://www.kaggle.com/competitions?listOption=active"  # 20 rows per &page=N


def _event(raw):
    title = raw.get("title") or raw.get("competitionTitle")
    slug = raw.get("ref") or raw.get("competitionSlug") or raw.get("slug")
    url = raw.get("url") or ("/competitions/" + slug if slug else None)
    start = dt(raw.get("dateEnabled") or raw.get("enabledDate") or raw.get("startDate"))
    end = dt(raw.get("deadline") or raw.get("competitionDeadline") or raw.get("endDate"))
    if not title or not url or not current(start, end):
        return None
    reward = raw.get("reward") or raw.get("prize")
    if isinstance(reward, dict):
        reward = reward.get("description")
    reward = str(reward) if reward is not None else None
    usd = None
    if reward and re.fullmatch(r"\$[\d,.]+", reward.strip()):
        usd = float(reward.strip().lstrip("$").replace(",", ""))
    # teamCount is teams, not people: never expose it as participants.
    return Event(source="kaggle", signals=source_signals("kaggle", raw), source_id=str(raw["id"]) if raw.get("id") else slug,
        title=title, url=urljoin("https://www.kaggle.com", url),
        description=plain(raw.get("description") or raw.get("subtitle")),
        start=start, end=end, registration_deadline=dt(raw.get("rulesDeadline")),
        format="online", organizer=raw.get("hostName") or raw.get("organizationName"),
        prize=reward, prize_usd=usd, tags=["ai"], kind="coding_competition",
        confidence=0.9, classified_by="source")


def collect() -> list[Event]:
    authenticated = bool(os.getenv("KAGGLE_USERNAME") and os.getenv("KAGGLE_KEY"))
    with client() as c:
        robots(c, API if authenticated else SOURCE["url"])
        if authenticated:
            events = {}
            for page in range(1, MAX_PAGES + 1):
                response = c.get(API, params={"page": page, "sortBy": "latestDeadline"},
                                 auth=(os.environ["KAGGLE_USERNAME"], os.environ["KAGGLE_KEY"]))
                if response.status_code in (401, 403, 429):
                    raise RuntimeError(f"blocked: Kaggle official API HTTP {response.status_code}")
                response.raise_for_status()
                if "json" not in response.headers.get("content-type", ""):
                    raise RuntimeError("blocked: Kaggle API returned non-JSON response")
                rows = response.json()
                if not isinstance(rows, list):
                    raise RuntimeError("Kaggle official API response changed: expected list")
                for raw in rows:
                    event = _event(raw)
                    if event:
                        events[event.url] = event
                if len(rows) < 20:
                    break
            else:
                warn_limit(__name__, "official API")
            return list(events.values())
    return browser_worker("kaggle")



def parse(html: str, base_url: str) -> list[Event]:
    """Keep cards explicitly marked ongoing/to-go; never invent relative dates."""
    from ._html_util import HTMLParser, objects, current
    events = {}
    for raw in objects(html):
        if any(k in raw for k in ('deadline', 'competitionDeadline', 'endDate')):
            event = _event(raw)
            if event and current(event.start, event.end):
                event.url = urljoin(base_url, raw.get('url') or event.url)
                events[event.url] = event
    tree = HTMLParser(html)
    # The overview has role=listitem cards; the paged Active list has plain li rows.
    for card in tree.css('[role="listitem"][aria-label], li[aria-label$=" List Item"]'):
        link = card.css_first('a[href*="/competitions/"]')
        if link is None:
            continue
        href = link.attributes.get('href', '')
        if not re.fullmatch(r'/competitions/[^/?#]+/?', href):
            continue
        text = card.text(separator=' ', strip=True)
        if not re.search(r'\b(?:Ongoing|(?:a|an|\d+) (?:day|week|month|year)s? to go)\b', text, re.I):
            continue
        url = urljoin(base_url, href)
        if url in events:
            continue
        prize = card.css_first('h2') or next((d for d in card.css('div') if re.fullmatch(r'\$[\d,]+', d.text(strip=True))), None)
        reward = prize.text(strip=True) if prize else None
        org = card.css_first('img[alt^="organized by "]')
        image = link.css_first('img[src]')
        paragraphs = link.css('p')
        description = next((p.text(separator=' ', strip=True) for p in paragraphs + link.css('span')
                            if len(p.text(strip=True)) > 20 and not re.search(r'Competition|Hackathon|Teams$|to go$', p.text(strip=True))), None)
        teams = re.search(r'\b([\d,]+) Teams\b', text, re.I)
        category = re.search(r'\b(Getting Started|Featured|Research|Playground|Community|Analytics)\b', text)
        events[url] = Event(source='kaggle', signals=source_signals('kaggle', {
            'description': description, 'reward': reward,
            'teamCount': teams[1].replace(',', '') if teams else None,
            'category': category[1] if category else None}), source_id=href.rstrip('/').split('/')[-1],
            title=re.sub(r' List Item$', '', card.attributes['aria-label']), url=url, description=description,
            format='online', organizer=org.attributes['alt'][13:] if org else None,
            image=urljoin(base_url, image.attributes['src']) if image else None,
            prize=reward, prize_usd=float(reward[1:].replace(',', '')) if reward and re.fullmatch(r'\$[\d,]+', reward) else None,
            tags=['ai'], kind='coding_competition', confidence=0.9, classified_by='source')
    return list(events.values())


def _collect() -> list[Event]:
    from ._html_util import load
    events = {}
    with cdp_page() as page:
        load(page, SOURCE['url'], '[role="listitem"][aria-label]')
        events.update((e.url, e) for e in parse(page.content(), page.url))
        # Active list: stop at the last page (no enabled next button) or one with nothing new.
        for n in range(1, MAX_PAGES + 1):
            load(page, f'{ACTIVE}&page={n}', 'a[href^="/competitions/"]')
            page.wait_for_timeout(1500)
            fresh = {e.url: e for e in parse(page.content(), page.url)}
            new = fresh.keys() - events.keys()
            events.update(fresh)
            nxt = page.locator('button[aria-label="Go to next page"]')
            if not new or not nxt.count() or nxt.first.is_disabled():
                break
        else:
            warn_limit(__name__, 'active list')
    return list(events.values())
