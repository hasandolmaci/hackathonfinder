"""HackQuest public GraphQL (the hackathons page's own query). Web3 buildathons: registration, submission and reward timeline."""
from hackfinder.models import Event
from ._signals_util import source_signals
from ._platforms_util import MAX_PAGES, absolute, check_robots, client, current, json_response, number, plain, utc, warn_limit

SOURCE = {"id": "hackquest", "name": "HackQuest", "url": "https://www.hackquest.io/hackathons",
          "method": "api", "default_kind": "hackathon"}
API = "https://api.hackquest.io/graphql"
LIMIT = 50
QUERY = """query Hackathons($page: Int, $limit: Int) { listHackathons(page: $page, limit: $limit) { total data {
  id name alias status participants projectCount totalRewards winnerCount ecosystem { type }
  info { host image intro levelTag mode teachStack description } judge { announce }
  timeline { submissionClose submissionOpen registrationClose registrationOpen }
  rewards { totalRewards currency } members { userId } } } }"""
USD = ("USD", "USDC", "USDT", "DAI")


def _event(row):
    time, info = row.get("timeline") or {}, row.get("info") or {}
    start, end = utc(time.get("submissionOpen") or time.get("registrationOpen")), utc(time.get("submissionClose"))
    deadline = utc(time.get("registrationClose"))
    if not row.get("alias") or not current(start, end or deadline):
        return None
    mode = (info.get("mode") or "").lower()
    fmt = {"online": "online", "offline": "in-person", "hybrid": "hybrid"}.get(mode, "unknown")
    currencies = {r.get("currency") for r in row.get("rewards") or [] if r.get("currency")}
    amount = number(row.get("totalRewards"))
    unit = currencies.pop() if len(currencies) == 1 else None
    prize = f"{amount:,.0f} {unit or 'USD'}" if amount else None
    tags = ["web3", *(info.get("teachStack") or []), *([info["levelTag"]] if info.get("levelTag") else []),
            *(f"ecosystem:{e['type']}" for e in row.get("ecosystem") or [] if e.get("type"))]
    if row.get("winnerCount"):
        tags.append(f"winners:{row['winnerCount']}")
    if row.get("projectCount"):
        tags.append(f"projects:{row['projectCount']}")
    return Event(source="hackquest", signals=source_signals("hackquest", row), source_id=str(row["id"]), title=plain(row["name"]),
        url=f"https://www.hackquest.io/hackathons/{row['alias']}", description=plain(info.get("intro") or info.get("description")),
        image=absolute(info.get("image"), SOURCE["url"]), start=start, end=end, registration_deadline=deadline,
        format=fmt, prize=prize, prize_usd=amount if amount and (unit or "USD") in USD else None,
        participants=row.get("participants"), organizer=plain(info.get("host")), tags=tags,
        kind="hackathon", confidence=0.9, classified_by="source")


def collect() -> list[Event]:
    events, seen = [], set()
    with client() as c:
        check_robots(c, SOURCE["url"])
        for page in range(1, MAX_PAGES + 1):
            data = json_response(c.post(API, json={"query": QUERY, "variables": {"page": page, "limit": LIMIT}}))
            block = ((data.get("data") or {}).get("listHackathons"))
            if not isinstance(block, dict) or not isinstance(block.get("data"), list):
                raise RuntimeError("HackQuest GraphQL no longer returns listHackathons")
            rows = [r for r in block["data"] if r["id"] not in seen]
            seen.update(r["id"] for r in rows)
            events += [e for e in map(_event, rows) if e]
            if not rows or page * LIMIT >= (block.get("total") or 0):
                break
        else:
            warn_limit(__name__)
    return events
