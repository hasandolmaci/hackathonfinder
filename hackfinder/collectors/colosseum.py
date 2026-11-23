"""Colosseum's Svelte public program state, including the open Eternal window."""
import re
import time
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from hackfinder.models import Event
from ._platforms_util import absolute, current, plain, utc
from ._signals_util import count, reward, signals
from ._vertical_util import client, polite_json, robots

SOURCE = {"id": "colosseum", "name": "Colosseum", "url": "https://colosseum.com/hackathon",
          "method": "api", "default_kind": "hackathon"}
API = SOURCE["url"] + "/__data.json"


def _state(data):
    # SvelteKit devalue JSON uses integer references into each node's value table.
    for node in data.get("nodes", []):
        values = (node or {}).get("data")
        if not isinstance(values, list) or not values:
            continue
        def expand(index):
            if index < 0:
                return None
            value = values[index]
            if isinstance(value, dict):
                return {k: expand(v) for k, v in value.items()}
            if isinstance(value, list):
                return value if value and isinstance(value[0], str) else [expand(v) for v in value]
            return value
        root = expand(0)
        if isinstance(root, dict) and isinstance(root.get("currentEvent"), dict):
            return root["currentEvent"]
    raise RuntimeError("Colosseum program state has no currentEvent")


def parse(state, pages):
    events = []
    for key, program in (state.get("programs") or {}).items():
        if key not in ("hackathon", "eternal") or not program.get("active"):
            continue
        phase = str(program.get("phase") or program.get("label") or "").lower()
        if phase in ("judging", "ended", "closed", "completed", "winners"):
            continue
        url = absolute(program.get("landingPageUrl"), SOURCE["url"])
        if not url:
            continue
        tree = HTMLParser(pages.get(url, ""))
        for n in tree.css("script, style"):
            n.decompose()
        text = (tree.css_first("main") or tree).text(separator=" ", strip=True)
        end = utc(program.get("endDate"))
        start = utc(program.get("startDate"))
        if not current(start, end):
            continue
        if key == "hackathon":
            target = utc(state.get("countdownTarget"))
            label = str(state.get("countdownLabel") or "").lower()
            if target and re.search("end|close|deadline", label):
                end = target
            elif target and re.search("start|begin|launch", label):
                start = target
        if not current(start, end):
            continue
        # The investment offer is separate from the Eternal Award cash prize.
        m = re.search(r"USDC\s+SEMI-ANNUAL AWARD\s+(\$[\d,]+)", text, re.I) if key == "eternal" else re.search(r"(?:prize pool|in prizes)\s*[:—-]?\s*(\$[\d,]+)", text, re.I)
        prize = m[1] if m else None
        cash = reward(prize)
        if key == "eternal" and cash:
            cash["prize_currency"] = "USDC"
        events.append(Event(source="colosseum", source_id=key + ":" + (program.get("endDate") or program.get("name") or url),
            url=url, title="Colosseum Eternal" if key == "eternal" else program.get("name") or state["name"],
            description=plain(text), start=start, end=end, registration_deadline=end if key == "eternal" else None,
            format="online", organizer="Colosseum", prize=prize, tags=["web3", "solana"],
            participants=count(program.get("participantCount") if key == "eternal" else state.get("participantCount")),
            signals=signals(text=text, registrations=count(program.get("participantCount") if key == "eternal" else state.get("participantCount")), **cash),
            kind="hackathon", confidence=0.9, classified_by="source"))
    return events


def collect():
    with client(timeout=20) as c:
        robots(c, SOURCE["url"])
        state = _state(polite_json(c, API))
        pages = {}
        for p in (state.get("programs") or {}).values():
            if p.get("active") and (u := absolute(p.get("landingPageUrl"), SOURCE["url"])):
                time.sleep(1.2)
                r = c.get(u)
                r.raise_for_status()
                pages[u] = r.text
        return parse(state, pages)
