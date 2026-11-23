"""Superteam Earn's promoted hackathon pages; never collect bounty/project listings."""
import json
import re
import time
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from hackfinder.models import Event
from ._platforms_util import absolute, current, plain, utc
from ._signals_util import count, money, signals
from ._vertical_util import client, robots

SOURCE = {"id": "superteam", "name": "Superteam Earn", "url": "https://superteam.fun/earn",
          "method": "api", "default_kind": "hackathon"}
RANKED_SEARCH = True  # Homepage promotions are not an exhaustive historical directory.


def links(html):
    return list(dict.fromkeys(u for n in HTMLParser(html).css("a[href]")
        if (u := absolute(n.attributes["href"], SOURCE["url"])) and re.search(r"/earn/hackathon/[^/?#]+/?$", u)))


def parse(html, url):
    node = HTMLParser(html).css_first("script#__NEXT_DATA__")
    if node is None:
        raise RuntimeError("Superteam hackathon page has no __NEXT_DATA__")
    r = json.loads(node.text()).get("props", {}).get("pageProps", {}).get("hackathon")
    if not isinstance(r, dict):
        raise RuntimeError("Superteam page no longer has hackathon data")
    start, end = utc(r.get("startDate")), utc(r.get("deadline"))
    if not (start or end) or not current(start, end):
        return []
    return [Event(source="superteam", source_id=r["id"], title=r["name"], url=url, start=start, end=end,
        registration_deadline=end, format="online", organizer=(r.get("Sponsor") or {}).get("name"),
        description=plain(r.get("description")), image=absolute(r.get("logo"), url),
        participants=count(r.get("participants")), prize=str(r["rewardAmount"]) + " " + r["token"] if r.get("rewardAmount") and r.get("token") else None,
        signals=signals(text=r.get("description"), registrations=count(r.get("participants")),
            **money(r.get("rewardAmount"), r.get("token"))), tags=["web3", "solana"],
        kind="hackathon", confidence=0.9, classified_by="source")]


def collect():
    events = []
    with client(timeout=20) as c:
        robots(c, SOURCE["url"])
        time.sleep(1.1)
        r = c.get(SOURCE["url"])
        r.raise_for_status()
        if not HTMLParser(r.text).css_first("script#__NEXT_DATA__"):
            raise RuntimeError("Superteam homepage no longer has public Next data")
        for url in links(r.text):
            time.sleep(1.2)
            r = c.get(url)
            r.raise_for_status()
            events.extend(parse(r.text, url))
    return events
