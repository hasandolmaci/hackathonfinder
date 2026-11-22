"""Live Unstop public opportunities JSON. This directory mixes event kinds."""
from collections import defaultdict

from hackfinder.models import Event
from ._signals_util import source_signals
from ._platforms_util import MAX_PAGES, absolute, check_robots, client, current, json_response, number, plain, utc, warn_limit

SOURCE = {"id": "unstop", "name": "Unstop", "url": "https://unstop.com/hackathons",
          "method": "api", "default_kind": "mixed"}
API = "https://unstop.com/api/public/opportunity/search-new"


def _kind(row):
    # online_coding_challenge is a generic Unstop subtype also assigned to
    # quizzes and build hackathons, so it cannot establish the event kind.
    labels = {str(x.get("name", "")).lower() for x in row.get("workfunction", [])}
    labels.update(str(x.get("name", "")).lower() if isinstance(x, dict) else str(x).lower()
                  for x in row.get("tags", []))
    for label, kind in (("ideathon", "ideathon"), ("hackathon", "hackathon"),
                        ("coding competition", "coding_competition"),
                        ("coding challenge", "coding_competition"),
                        ("quizzes & treasure hunt", "other"), ("conferences", "other")):
        if any(label in x for x in labels):
            return kind
    return "unknown"


def _prizes(rows):
    totals, extras = defaultdict(float), []
    for p in rows:
        cash = number(p.get("cash"))
        currency = p.get("currencyCode")
        # 'cash' on in-kind rewards is often a membership's advertised value.
        if cash and currency and p.get("prize_type") == "cash" and not p.get("cash_postfix"):
            totals[currency] += cash
        elif cash and currency:
            extras.append(f"{currency} {cash:,.0f}{p.get('cash_postfix') or ''} ({p.get('prize_type') or 'reward'})")
        elif p.get("others"):
            extras.append(plain(p["others"], 100))
        elif p.get("certificate"):
            extras.append("Certificates")
    text = [f"{currency} {amount:,.0f}" for currency, amount in totals.items()]
    text.extend(dict.fromkeys(x for x in extras if x))
    return "; ".join(text)[:500] or None, totals.get("USD")


def _event(row):
    start, end = utc(row.get("start_date")), utc(row.get("end_date"))
    if not current(start, end):
        return None
    mode = {"online": "online", "offline": "in-person", "hybrid": "hybrid"}.get(row.get("region"), "unknown")
    address = row.get("address_with_country_logo") or {}
    country = address.get("country") or {}
    country = country.get("name") if isinstance(country, dict) else country
    location = ", ".join(dict.fromkeys(x for x in (address.get("city"), address.get("state"), country) if x))
    prize, usd = _prizes(row.get("prizes") or [])
    kind = _kind(row)
    return Event(source="unstop", signals=source_signals("unstop", row), source_id=str(row["id"]), title=plain(row["title"]),
        url=absolute(row.get("seo_url") or row.get("public_url"), "https://unstop.com/"),
        description=plain(row.get("details")), image=absolute(row.get("logoUrl2"), SOURCE["url"]),
        start=start, end=end, registration_deadline=utc((row.get("regnRequirements") or {}).get("end_regn_dt")),
        format=mode, location=None if mode == "online" else location or plain(address.get("address")),
        country=country if mode != "online" else None, prize=prize, prize_usd=usd,
        participants=row.get("registerCount"), organizer=plain((row.get("organisation") or {}).get("name")),
        tags=list(dict.fromkeys(x["name"] for x in row.get("workfunction", []) if x.get("name"))),
        kind=kind, confidence=0.9 if kind != "unknown" else 0.0,
        classified_by="source" if kind != "unknown" else "none")


def collect() -> list[Event]:
    result, seen = [], set()
    with client() as c:
        check_robots(c, API)
        for page in range(1, MAX_PAGES + 1):
            data = json_response(c.get(API, params={"opportunity": "hackathons", "oppstatus": "open",
                                                   "per_page": 100, "page": page})).get("data", {})
            rows = data.get("data")
            if not isinstance(rows, list):
                raise RuntimeError("Unstop JSON no longer contains data.data")
            fresh = [row for row in rows if row["id"] not in seen]
            for row in fresh:
                seen.add(row["id"])
                event = _event(row)
                if event:
                    result.append(event)
            if page >= data.get("last_page", 1) or not fresh:
                break
        else:
            warn_limit(__name__)
    return result
