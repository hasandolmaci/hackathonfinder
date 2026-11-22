"""Keep observed scoring evidence; absent fields stay absent, including flags."""
import re
import json
import math

from ._platforms_util import number, plain


def signals(*, text=None, **values):
    result = {k: v for k, v in values.items() if v is not None}
    if text:
        text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>|<!--.*?-->", " ", str(text), flags=re.I | re.S)
        text = plain(text, 3000)
        if text:
            result["text"] = text
    return result


def count(value):
    n = number(value)
    return int(n) if n is not None and math.isfinite(n) and n >= 0 and n.is_integer() and not isinstance(value, bool) else None


def flag(value):
    return bool(value) if isinstance(value, (bool, int)) and value in (0, 1) else None


def names(rows):
    return list(dict.fromkeys(n for r in rows or [] if (n := plain(r.get("name") if isinstance(r, dict) else r))))


def money(amount, currency):
    amount = number(amount)
    return {"prize_amount": amount, "prize_currency": currency} if amount is not None and math.isfinite(amount) and amount >= 0 and currency else {}


def reward(text):
    """Read an explicit currency amount, never a sum of currencies or perk values."""
    text = plain(text.get("description") if isinstance(text, dict) else text, 3000) or ""
    units = set(re.findall(r"\b(?:USD|INR|EUR|GBP|ZAR|USDC|USDT|DAI)\b", text))
    units.update(code for symbol, code in (("₹", "INR"), ("€", "EUR"), ("£", "GBP")) if symbol in text)
    if len(units) > 1:
        return {}
    unit = next(iter(units), None)
    for symbol, code in (("₹", "INR"), ("€", "EUR"), ("£", "GBP"), ("$", "USD")):
        if symbol in text:
            unit = unit or code
            break
    if not unit:
        return {}
    m = re.search(r"(?:[$₹€£]|\b(?:USD|INR|EUR|GBP|ZAR|USDC|USDT|DAI)\b)\s*(\d[\d,]*(?:\.\d+)?(?: \d{3})*)", text)
    if not m:
        m = re.search(r"([\d][\d, .]*)\s*(?:USD|INR|EUR|GBP|ZAR|USDC|USDT|DAI)\b", text)
    if not m:
        return {}
    # Abbreviated totals need source-specific handling, not a guessed multiplier.
    tail = text[m.end():].lstrip()
    if re.match(r"(?:[kmb]\b|lakh|crore|million|billion)", tail, re.I):
        return {}
    if re.match(r"(?:in\s+)?(?:credits?|vouchers?|hardware|swags?)\b", tail, re.I):
        return {}
    return money(m[1].replace(" ", ""), unit)


def noncash(text):
    return True if re.search(r"\b(?:credits?|swags?|hardware|vouchers?|memberships?|certificates?)\b", text or "", re.I) else None


def cash_prizes(rows):
    """Devfolio prose must explicitly call an amount cash; ignore parent totals."""
    parents = {p.get("parent_prize_uuid") for p in rows if p.get("parent_prize_uuid")}
    totals = {}
    for p in rows:
        desc = plain(p.get("desc"), 3000) or ""
        if p.get("uuid") in parents or not re.match(r"^Cash prize of\s", desc, re.I):
            continue
        cash = reward(desc)
        if cash and not noncash(desc):
            unit = cash["prize_currency"]
            totals[unit] = totals.get(unit, 0) + cash["prize_amount"]
    return money(next(iter(totals.values())), next(iter(totals))) if len(totals) == 1 else {}


def source_signals(source, row, detail=None):
    """Map public listing fields to the shared vocabulary without inferred defaults."""
    d = detail or {}
    if source == "devpost":
        return signals(registrations=count(row.get("registrations_count")), featured=flag(row.get("featured")),
            official=flag(row.get("managed_by_devpost_badge")), invite_only=flag(row.get("invite_only")),
            themes=names(row["themes"]) if isinstance(row.get("themes"), list) else None,
            prize_noncash=True if (row.get("prizes_counts") or {}).get("other", 0) > 0 else None,
            **reward(row.get("prize_amount")))
    if source == "devfolio":
        sponsors = [s for tier in row.get("sponsor_tiers") or [] for s in tier.get("sponsors") or []]
        text = "\n".join([row.get("desc") or row.get("tagline") or "",
            *[str(f.get("answer") or "") for f in row.get("hackathon_faqs") or []]])
        return signals(text=text, registrations=count(row.get("participants_count")),
            official=flag(row.get("devfolio_official")), verified=flag(row.get("verified")), featured=flag(row.get("featured")),
            women_only=flag((row.get("hackathon_setting") or {}).get("women_only")),
            entries=count(row.get("projects_submitted")), judges=len(row["judges"]) if isinstance(row.get("judges"), list) else None,
            sponsors=names(sponsors) if isinstance(row.get("sponsor_tiers"), list) else None,
            themes=names(row["themes"]) if isinstance(row.get("themes"), list) else None,
            prize_noncash=noncash(" ".join(str(p.get("desc") or "") for p in row.get("prizes") or [])),
            **cash_prizes(row.get("prizes") or []))
    if source == "unstop":
        eligibility = (row.get("regnRequirements") or {}).get("eligibility") or {}
        if isinstance(eligibility, str):
            try:
                eligibility = json.loads(eligibility)
            except ValueError:
                eligibility = {}
        sectors = eligibility.get("sector") if isinstance(eligibility, dict) else None
        totals = {}
        for p in row.get("prizes") or []:
            if p.get("prize_type") == "cash" and not p.get("cash_postfix") and p.get("currencyCode") and number(p.get("cash")) is not None:
                unit = p["currencyCode"]
                totals[unit] = totals.get(unit, 0) + number(p["cash"])
        cash = money(next(iter(totals.values())), next(iter(totals))) if len(totals) == 1 else {}
        return signals(text=row.get("details"), registrations=count(row.get("registerCount")),
            paid_entry=flag(row.get("isPaid")), hiring=flag(row.get("actively_hiring")),
            students_only=set(sectors) == {"students"} if isinstance(sectors, list) and sectors else None,
            region_locked=bool(eligibility.get("locations")) if isinstance(eligibility, dict) and eligibility.get("location_type") not in (None, "all") else None,
            prize_noncash=True if any(p.get("others") or p.get("certificate") or p.get("prize_type") == "in_kind" for p in row.get("prizes") or []) else None,
            **cash)
    if source == "ctftime":
        restriction = str(row.get("restrictions") or "").lower()
        return signals(text=row.get("description"), ctf_weight=number(row.get("weight")), ctf_id=count(row.get("ctf_id")),
            teams=count(row.get("participants")), series_id=str(row["ctf_id"]) if row.get("ctf_id") is not None else None,
            students_only=True if restriction in ("academic", "students only") else None,
            invite_only=True if "invite" in restriction else False if restriction == "open" else None,
            **reward(row.get("prizes")))
    if source == "itchio":
        hosts = row.get("hosts")
        return signals(text=row.get("description") or row.get("short_text") or row.get("text"),
            joined=count(row.get("joined")), entries=count(row.get("entries")),
            featured=flag(row.get("featured")),
            hosts=names(hosts) if isinstance(hosts, list) else [hosts] if hosts else None)
    if source == "kaggle":
        category = row.get("category")
        return signals(text=row.get("description") or row.get("subtitle"), teams=count(row.get("teamCount")),
            kaggle_category=category if isinstance(category, str) else None, **reward(row.get("reward") or row.get("prize")))
    if source == "taikai":
        return signals(text=row.get("shortDescription"), registrations=count(row.get("participantsCount")),
            **money(row.get("prize"), (row.get("prizeCurrency") or {}).get("name")))
    if source == "hackclub":
        return signals(mlh_member=flag(row.get("mlhAssociated")), official=flag(row.get("hack_club_event")))
    if source == "hackerearth":
        return signals(text=row.get("description"), students_only=flag(row.get("college")))
    if source == "devnovate":
        text = "\n".join([row.get("subtitle") or "", *[r for r in row.get("rules") or [] if isinstance(r, str)]])
        return signals(text=text, registrations=count(row.get("numberOfRegistrations")),
            featured=flag(row.get("isFeatured")), verified=flag(row.get("verified")), paid_entry=flag(row.get("paid")),
            entry_fee=str(row["price"]) if row.get("paid") and row.get("price") is not None else None,
            themes=names(row["theme"]) if "theme" in row else None,
            prize_noncash=noncash(row.get("prizePool")), **reward(row.get("prizePool")))
    if source == "hack2skill":
        tags = row.get("tags") or {}
        ticket = (tags.get("ticket") or {}).get("value")
        text = "\n".join(str(item.get("description") or "") for section in d.get("sections") or []
            if section.get("type") in ("ABOUT", "RULES", "FAQS") and not section.get("isHidden")
            for category in section.get("category") or [] if not category.get("isHidden")
            for item in category.get("data") or [] if not item.get("isHidden"))
        return signals(text=text or d.get("description"), registrations=count((tags.get("registrations") or {}).get("value")),
            paid_entry=False if ticket == "FREE" else True if ticket == "PAID" else None,
            region_locked=bool(tags["region"].get("value")) if isinstance(tags.get("region", {}).get("value"), list) else None)
    if source == "zindi":
        return signals(text=row.get("description") or row.get("subtitle"), registrations=count(row.get("participations_count")),
            invite_only=flag(row.get("secret_code_required")), **reward(row.get("reward")))
    if source == "dorahacks":
        return signals(text=d.get("description"), registrations=count(row.get("hackers_count")),
            entries=count(row.get("buidls_count")), tracks=count(d.get("tracks_count")),
            **money(row.get("bonus_price"), row.get("bonus_token")))
    if source == "hackquest":
        info = row.get("info") or {}
        units = {r["currency"] for r in row.get("rewards") or [] if r.get("currency")}
        return signals(text=info.get("description") or info.get("intro"), registrations=count(row.get("participants")),
            entries=count(row.get("projectCount")), judges=len(row["judge"]) if isinstance(row.get("judge"), list) else None,
            **money(row.get("totalRewards"), next(iter(units)) if len(units) == 1 else None))
    if source == "commudle":
        # number_of_participants is the configured limit, not the interested/registered count.
        prizes = row.get("total_prize_amount") or {}
        return signals(text=row.get("description") or row.get("tagline"), capacity=count(row.get("number_of_participants")),
            themes=[row["hackathon_theme"]] if row.get("hackathon_theme") else None,
            **(money(next(iter(prizes.values())), next(iter(prizes))) if len(prizes) == 1 else {}))
    if source == "encodeclub":
        return signals(text=row.get("about_content") or row.get("tagline"), registrations=count(row.get("total_registrations")),
            featured=flag(row.get("featured")))
    if source == "wemakedevs":
        return signals(text=row.get("prize"), series_id=row.get("seriesSlug"),
            prize_noncash=noncash(row.get("prize")), **reward((row.get("prize") or "").replace("$$", "$")))
    if source == "hackjunction":
        return signals(text=row.get("description"), featured=flag(row.get("isFeatured")))
    if source == "ethglobal":
        return signals(text=row.get("description") or row.get("tagline"), hosts=["ETHGlobal"])
    if source == "globalgamejam":
        return signals(hosts=["Global Game Jam"], series_id="globalgamejam")
    if source == "eventbrite":
        return signals(text=row.get("full_description") or d.get("description") or row.get("summary"),
            series_id=str(row["series_id"]) if row.get("series_id") is not None else None,
            invite_only=flag(row.get("is_protected_event")))
    if source == "allhackathons":
        return signals(text=d.get("text") or d.get("description") or row.get("description"),
            themes=d.get("themes") or row.get("themes"), **reward(d.get("prize")))
    return signals(text=row.get("description") or row.get("desc"))
