"""DoraHacks hub JSON, read through the browser (an AWS WAF JS challenge blocks plain HTTP)."""
import json
import re
from datetime import datetime, timezone

from hackfinder.browser import cdp_page
from hackfinder.models import Event
from ._signals_util import source_signals
from ._vertical_util import MAX_PAGES, browser_worker, check_block, plain, warn_limit

SOURCE = {"id": "dorahacks", "name": "DoraHacks", "url": "https://dorahacks.io/hackathon",
          "method": "scrape", "default_kind": "hackathon"}
API = "https://dorahacks.io/api/v1/hub/hackathons"
PAGE_SIZE = 50
USD = ("USD", "USDT", "USDC", "DAI")
FORMATS = {"virtual": "online", "irl": "in-person", "hybrid": "hybrid"}


def collect() -> list[Event]:
    return browser_worker("dorahacks")


def _stamp(value):
    return datetime.fromtimestamp(value, timezone.utc) if isinstance(value, (int, float)) and value > 0 else None


def _markdown(text):
    """Drop markdown markup so the description reads as plain text."""
    return re.sub(r"[#*`>|]+", " ", re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text or ""))


def _event(row, detail=None):
    """One hub row (optionally merged with its detail record) -> Event."""
    start, end = _stamp(row.get("timeline_start")), _stamp(row.get("timeline_end"))
    slug = row.get("uname") or row.get("id")  # Some hackathons have no uname; their page is /hackathon/<id>.
    if not slug or not row.get("title") or not (start or end):
        return None
    detail = detail or {}
    price, token = row.get("bonus_price"), row.get("bonus_token") or "USD"
    prize = f"{price:,.0f} {token}" if price else None
    fmt = FORMATS.get((row.get("venue_form") or "").lower(), "unknown")
    venue = (row.get("venue_name") or "").strip()
    location = None if fmt == "online" or not venue or venue.lower().startswith("to be announced") else venue
    tags = ["web3", *[t.strip() for t in (row.get("tags") or "").split(",") if t.strip()],
            *[t.strip() for t in (row.get("ecosystem") or "").split(",") if t.strip()]]
    if detail.get("tracks_count"):
        tags.append(f"tracks:{detail['tracks_count']}")
    if row.get("buidls_count"):
        tags.append(f"submissions:{row['buidls_count']}")
    return Event(source="dorahacks", signals=source_signals("dorahacks", row, detail), source_id=str(row["id"]), title=plain(row["title"]),
        url=f"https://dorahacks.io/hackathon/{slug}", image=row.get("image_url") or None,
        description=plain(_markdown(detail.get("description"))), start=start, end=end, format=fmt, location=location,
        prize=prize, prize_usd=float(price) if price and token.upper() in USD else None,
        participants=row.get("hackers_count"), organizer=plain((row.get("owner") or {}).get("name")),
        tags=list(dict.fromkeys(tags)), kind="hackathon", confidence=0.9, classified_by="source")


def _get(page, url):
    reply = page.evaluate("async u => { const r = await fetch(u); return {status: r.status, text: await r.text()}; }", url)
    if reply["status"] in (401, 403, 405, 429):
        raise RuntimeError(f"blocked: HTTP {reply['status']} from {url}")
    try:
        return json.loads(reply["text"])
    except ValueError:
        raise RuntimeError(f"DoraHacks returned non-JSON from {url}") from None


def _collect():
    events, seen = {}, set()
    with cdp_page() as page:
        page.goto(SOURCE["url"], wait_until="domcontentloaded", timeout=30000)
        for _ in range(20):  # The automatic JS challenge resolves by itself; a real CAPTCHA does not.
            if "human verification" not in page.title().lower():
                break
            page.wait_for_timeout(1000)
        else:
            raise RuntimeError("blocked: AWS WAF human verification did not clear automatically")
        check_block(page)
        for status in ("ongoing", "upcoming"):
            for n in range(1, MAX_PAGES + 1):
                data = _get(page, f"{API}?status={status}&page={n}&page_size={PAGE_SIZE}")
                rows = data.get("results")
                if not isinstance(rows, list):
                    raise RuntimeError("DoraHacks hub JSON no longer contains results")
                fresh = [r for r in rows if r["id"] not in seen]
                seen.update(r["id"] for r in fresh)
                for row in fresh:
                    try:
                        detail = _get(page, f"{API}/{row.get('uname') or row['id']}")
                    except RuntimeError:
                        detail = None
                    event = _event(row, detail)
                    if event and (event.end is None or event.end >= datetime.now(timezone.utc)):
                        events[event.url] = event
                    page.wait_for_timeout(250)
                if not fresh or not data.get("next"):
                    break
            else:
                warn_limit(__name__, status)
    return sorted(events.values(), key=lambda e: (e.start is None, e.start))
