"""Hackfinder Score: transparent evidence, cohort shrinkage, and factual explanations."""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
import json
import math
from pathlib import Path
import re
from statistics import median
from functools import lru_cache

VERSION = "1.1"
# Missing dimensions retain 15% weight; organizer keeps its full neutral anchor.
# Observed dimensions retain full weight, then all effective weights normalize.
UNKNOWN_MASS = .15
PRIOR_MASS = 10
SIZE_COHORT_MASS = 20
HALO_QUANTILE = .65
# Monotone display calibration for build events, fitted to the November 2026 crawl.
# Keep the middle neutral and separate strong evidence at the upper end.
BUILD_SCALE = ((0, 20), (40, 43), (55, 56), (57, 59.5), (60, 60.5),
               (65, 65), (71.5, 80), (90, 89), (100, 100))
SOURCE_NAMES = {"devpost": "Devpost", "devfolio": "Devfolio", "luma": "Luma",
                "ctftime": "CTFtime", "itchio": "itch.io", "hackquest": "HackQuest", "devnovate": "Devnovate",
                "hackclub": "Hack Club", "encodeclub": "Encode Club"}
DIMS = ("organizer", "community", "rewards", "support", "accessibility")
WEIGHTS = {kind: dict(zip(DIMS, values)) for kind, values in {
    "hackathon": (30, 20, 20, 20, 10), "ideathon": (30, 20, 20, 20, 10),
    "game_jam": (25, 35, 10, 15, 15), "ctf": (40, 25, 10, 10, 15),
    "coding_competition": (25, 20, 40, 0, 15), "other": (30, 20, 20, 20, 10),
    "unknown": (30, 20, 20, 20, 10)}.items()}
REPUTATION = json.loads(Path(__file__).with_name("reputation.json").read_text(encoding="utf-8-sig"))
COUNTS = {"registrations", "guests", "rsvps", "teams", "joined", "entries", "capacity", "participants"}
# Units per EUR; used only when the cached ECB table is unavailable.
STATIC_RATES = {"EUR": 1, "USD": 1.08, "GBP": .85, "INR": 90, "JPY": 163, "CAD": 1.47,
                "AUD": 1.63, "CHF": .96, "CNY": 7.8, "SGD": 1.46, "BRL": 5.5}
PATTERNS = {
    "travel_support": r"travel (?:reimbursement|stipend|grant|support|scholarship)|flights? (?:covered|reimbursed)|(?:accommodation|lodging) (?:provided|covered)",
    "hiring": r"hiring|internships?|job offers?|recruit(?:ers|ing)|interviews?|pre-placement|PPO",
    "mentors": r"mentors?|mentorship|workshops?|tech talks?",
    "food_swag": r"free (?:food|meals)|meals (?:provided|included)|swag|t-?shirts?|goodies",
    "prize_noncash": r"(?:cloud|api) credits|\$[\d,]+ in credits",
    "students_only": r"(?:only|exclusively) for students|must be (?:an? )?(?:enrolled )?student|open to (?:university|college|high school) students",
    "region_locked": r"open (?:only )?to (?:residents|citizens) of|only (?:for|open to) (?:teams|participants) (?:from|in|based in)",
}


@lru_cache(maxsize=8192)
def brands(text, tier):
    return [name for name, aliases in REPUTATION[tier].items()
            if any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text, re.I)
                   for alias in [name, *aliases])]


def extract(event):
    signals = dict(event.signals)
    text = " ".join([event.title, event.description or "", str(signals.get("text", ""))[:3000],
                     " ".join(event.tags), " ".join(signals.get("themes", []))])
    for key, pattern in PATTERNS.items():
        matches = list(re.finditer(r"\b(?:" + pattern + r")\b", text, re.I))
        if matches and key not in signals:
            signals[key] = any(not set(re.findall(r"\w+", re.split(r"[.;!?\n]", text[:m.start()].casefold())[-1])[-4:]) &
                               {"no", "not", "unfortunately", "without"} for m in matches)
    sponsors = set(signals.get("sponsors", []))
    for match in re.finditer(r"(?:sponsored by|powered by|in partnership with|partners?\s*:)([^.;\n]{1,250})", text, re.I):
        if not set(re.findall(r"\w+", text[:match.start()].casefold())[-4:]) & {"no", "not", "without"}:
            sponsors.update(brands(match[1], "A") + brands(match[1], "B"))
    if sponsors:
        signals["sponsors"] = sorted(sponsors)
    return signals


def size_values(event):
    values = {}
    for key in sorted(COUNTS, key=lambda k: k == "capacity"):
        if key == "capacity" and (values or event.participants is not None):
            continue
        value = event.signals.get(key)
        if isinstance(value, dict):
            for source, count in value.items():
                if isinstance(count, (int, float)) and count >= 0 and not (source == "luma" and count == 0):
                    values[source] = max(values.get(source, 0), count * (.25 if key == "capacity" else 1))
        elif isinstance(value, (int, float)) and value >= 0 and not (event.source == "luma" and value == 0):
            values[event.source] = max(values.get(event.source, 0), value * (.25 if key == "capacity" else 1))
    if event.participants is not None and not values and event.participants >= 0 and not (event.source == "luma" and event.participants == 0):
        values[event.source] = event.participants
    return values


def prize_usd(event, rates=None):
    if event.prize_usd is not None:
        return max(0, event.prize_usd)
    rates = rates or STATIC_RATES
    amount, currency = event.signals.get("prize_amount"), str(event.signals.get("prize_currency", "")).upper()
    if isinstance(amount, (int, float)) and currency in {"USDC", "USDT"}:
        return max(0, amount)
    if isinstance(amount, (int, float)) and currency in rates:
        return max(0, amount) * rates["USD"] / rates[currency]
    return None


def normalized(value):
    return " ".join(re.findall(r"\w+", (value or "").casefold()))


def observations(event, cohorts=None, rates=None, editions=0):
    s = extract(event)
    obs, reasons = {}, []
    organizer = event.organizer or ""
    # A host's venue or affiliation is not the reviewed organization itself.
    tier_a = any(normalized(organizer) == normalized(alias)
                 for name, aliases in REPUTATION["A"].items() for alias in [name, *aliases])
    tier_a = tier_a or event.source == "ethglobal"
    member = s.get("mlh_member") or event.source == "mlh"
    tier_b = bool(brands(organizer, "B"))
    prestige = 100 if tier_a else 67 if tier_b else 65 if member else 45 if organizer else None
    if tier_a:
        reasons.append(f"Tier-A organizer: {organizer or 'ETHGlobal'}")
    elif member:
        reasons.append("MLH member event")
    for flag, points in (("official", 85), ("verified", 70), ("featured", 75)):
        if s.get(flag):
            if flag == "featured" and event.source in {"luma", "meetup", "eventbrite"}:
                points = 50
            prestige = max(prestige or 0, points)
            platform = SOURCE_NAMES.get(event.source, event.source)
            reasons.append(f"Run by {organizer or platform} (official)" if flag == "official" else
                           f"{flag.title()} on {platform}")
    sponsor_text = " ".join(s.get("sponsors", []))
    if brands(sponsor_text, "A") or brands(sponsor_text, "B"):
        prestige = max(prestige or 0, 65)
    if s.get("ctf_weight") is not None:
        prestige = max(prestige or 0, min(100, 35 + 65 * math.log1p(max(0, s["ctf_weight"])) / math.log(101)))
    if s.get("kaggle_category"):
        prestige = max(prestige or 0, {"featured": 85, "research": 80, "recruitment": 75,
                                      "community": 45, "gettingstarted": 40}.get(normalized(str(s["kaggle_category"])).replace(" ", ""), 50))
    marker = bool(re.search(r"\b(?:20\d{2}|\d+(?:st|nd|rd|th)|v\d+)\b", event.title, re.I))
    if prestige is not None or editions or marker:
        obs["organizer"] = min(100, (prestige or 45) + min(10, editions * 2 + marker * 2))
    sizes = size_values(event)
    if sizes:
        scores = []
        for source, n in sizes.items():
            pool = (cohorts or {}).get((source, event.kind), [])
            percentile = 100 * bisect_right(pool, n) / len(pool) if pool else 100 * min(1, math.log1p(n) / math.log(5001))
            absolute = 100 * min(1, math.log1p(n) / math.log(5001))
            reliability = len(pool) / (len(pool) + SIZE_COHORT_MASS)
            scores.append(.6 * reliability * percentile + (1 - .6 * reliability) * absolute)
        obs["community"] = max(scores)
        if event.participants is None and not any(k in event.signals for k in COUNTS - {"capacity"}):
            obs["community"] = min(35, obs["community"])
        if event.participants is None and not any(k in event.signals for k in COUNTS - {"capacity"}):
            reasons.append("Capacity published (weak size evidence)")
        else:
            source = max(sizes, key=sizes.get)
            count = sizes[source]
            count_type = "participants"
            for key in ("registrations", "guests", "teams", "joined", "rsvps", "entries", "participants"):
                raw = event.signals.get(key)
                if (raw.get(source) if isinstance(raw, dict) else raw if source == event.source else None) == count:
                    count_type = "RSVPs" if key == "rsvps" else key
                    break
            if count == 1 and count_type.endswith("s"):
                count_type = count_type[:-1]
            reasons.append(f"{count:,.0f} {count_type} on {SOURCE_NAMES.get(source, source)}")
    prize = prize_usd(event, rates)
    if prize is not None:
        obs["rewards"] = 100 * min(1, math.log1p(prize) / math.log(250001))
        reasons.append(f"${prize:,.0f} prize pool")
    elif s.get("prize_noncash"):
        obs["rewards"] = 35
        reasons.append("Non-cash prizes offered")
    support_keys = ("sponsors", "travel_support", "hiring", "mentors", "food_swag")
    if any(k in s for k in support_keys):
        obs["support"] = min(100, 40 + min(29, len(s.get("sponsors", [])) * 10) +
                             sum(points for k, points in zip(support_keys[1:], (15, 8, 10, 3)) if s.get(k)))
        if s.get("travel_support"):
            reasons.append("Travel support offered")
    restrictions = ("invite_only", "women_only", "students_only", "paid_entry", "region_locked")
    if event.format != "unknown" or any(k in s for k in restrictions):
        obs["accessibility"] = (90 if event.format in {"online", "hybrid"} else 80) + (5 if s.get("paid_entry") is False else 0)
        obs["accessibility"] -= sum(points for k, points in zip(restrictions, (8, 3, 3, 10, 5)) if s.get(k))
    return obs, reasons, tier_a, s


class Context:
    """A rolling source/kind cohort, computed once per merge."""

    def __init__(self, events=(), history=(), rates=None):
        events = list(events)
        self.rates = rates or STATIC_RATES
        self.sizes = defaultdict(list)
        self.priors = defaultdict(list)
        self.history = list(history)
        self.coverage = defaultdict(lambda: defaultdict(int))
        self.totals = defaultdict(int)
        for event in events:
            for source, n in size_values(event).items():
                self.sizes[source, event.kind].append(n)
        for values in self.sizes.values():
            values.sort()
        for event in events:
            obs, _, _, _ = observations(event, self.sizes, self.rates)
            self.totals[event.source, event.kind] += 1
            for dim, value in obs.items():
                self.coverage[event.source, event.kind][dim] += 1
                self.priors[event.source, event.kind, dim].append(value)
                self.priors[None, event.kind, dim].append(value)

    def prior(self, event, dim, halo):
        values = sorted(self.priors.get((event.source, event.kind, dim), []))
        value = median(values) if values else 45
        prior = (len(values) * value + PRIOR_MASS * 45) / (len(values) + PRIOR_MASS)
        if halo:
            # Back off to observed kind-wide evidence when the source is sparse.
            pool = values if len(values) >= PRIOR_MASS else sorted(self.priors.get((None, event.kind, dim), []))
            if pool:
                position = (len(pool) - 1) * HALO_QUANTILE
                lower = int(position)
                quantile = pool[lower] + (pool[min(lower + 1, len(pool) - 1)] - pool[lower]) * (position - lower)
                prior = max(prior, (len(pool) * quantile + PRIOR_MASS * 45) / (len(pool) + PRIOR_MASS))
        return prior


    def editions(self, event):
        organizer = normalized(event.organizer)
        series = event.signals.get("series_id")
        return len({(old.start.date() if old.start else None, normalized(old.title)) for old in self.history
                    if old.url != event.url and old.start and event.start and old.start < event.start
                    and ((series and series == old.signals.get("series_id")) or
                         (organizer and organizer == normalized(old.organizer)))})


def score_event(event, context=None):
    context = context or Context()
    obs, reasons, halo, signals = observations(event, context.sizes, context.rates, context.editions(event))
    weights = WEIGHTS[event.kind]
    dims = {dim: round((9 * obs[dim] + context.prior(event, dim, halo)) / 10, 2) if dim in obs
            else round(context.prior(event, dim, halo), 2) for dim in DIMS}
    evidence = min(100, sum(weights[d] * .7 for d in obs) +
                   10 * bool(event.start) + 5 * bool(event.end) + 5 * bool(event.image) +
                   10 * (len(str(signals.get("text", "")) or event.description or "") >= 150) +
                   5 * bool(event.location or event.format == "online") + 5 * bool(event.also_on))
    effective = {d: weights[d] * (1 if d in obs or d == "organizer" else UNKNOWN_MASS) for d in DIMS}
    raw_value = sum(dims[d] * effective[d] for d in DIMS) / sum(effective.values())
    if event.kind in {"hackathon", "ideathon"}:
        for (left, low), (right, high) in zip(BUILD_SCALE, BUILD_SCALE[1:]):
            if left <= raw_value <= right:
                raw_value = low + (raw_value - left) * (high - low) / (right - left)
                break
    value = round(raw_value) if evidence >= 30 else None
    # Non-building listings have no demonstrated participant value as hackathons.
    if event.kind == "other" and value is not None:
        value = min(value, 35)
    missing = [d for d in DIMS if d not in obs and weights[d]]
    if not reasons:
        reasons = [f"{event.format.title()} event"] if event.format != "unknown" else []
    if event.organizer and not reasons:
        reasons.append(f"Run by {event.organizer}")
    if not reasons and event.start:
        reasons.append("Event dates published")
    # Counts and rewards carry more information than multiple platform badges.
    reasons.sort(key=lambda reason: 0 if re.match(r"[\d$]", reason) else
                 1 if reason == "Travel support offered" else 2)
    if value is None:
        reasons.insert(0, "Not enough info")
    return {"score": value, "score_tier": tier(value),
            "score_confidence": "high" if evidence >= 70 else "medium" if evidence >= 40 else "low",
            "score_detail": {"dims": dims, "weights": weights, "evidence": round(evidence),
                             "reasons": reasons[:3], "missing": missing, "effective_weights": effective, "version": VERSION}}


def tier(value):
    return "unknown" if value is None else "great" if value >= 80 else "good" if value >= 60 else "fair" if value >= 40 else "low"


def methodology():
    inputs = ["Reviewed organizer/brand, platform flags, past editions, CTF weight, Kaggle category",
              "Per-source/kind percentile (up to 60%, shrunk with 20 pseudo-observations) blended with log size; never summed",
              "Logarithmic USD cash prize; non-cash prizes capped at 35",
              "Explicit sponsors, travel support, hiring, mentors/workshops, food/swag",
              "Format, free entry, eligibility restrictions"]
    return {"version": VERSION, "dimensions": [{"id": d, "name": d.title(),
            "weight_by_kind": {k: w[d] for k, w in WEIGHTS.items()}, "inputs": [inputs[i]]} for i, d in enumerate(DIMS)],
            "tiers": [{"id": name, "min": low, "max": high} for name, low, high in
                      [("great", 80, 100), ("good", 60, 79), ("fair", 40, 59), ("low", 0, 39), ("unknown", None, None)]],
            "reputation_tiers": {k: list(v) for k, v in REPUTATION.items()},
            "calibration": {"build_scale": BUILD_SCALE, "unknown_mass": UNKNOWN_MASS,
                            "prior_mass": PRIOR_MASS, "size_cohort_mass": SIZE_COHORT_MASS,
                            "halo_quantile": HALO_QUANTILE},
            "notes": ["Open rules and statistics, not AI. No location or deadline bonus.",
                      "Observed dimensions use 90% evidence and 10% prior. Missing dimensions retain 15% weight, except the organizer anchor; effective weights normalize. Tier A raises priors to the observed cohort 65th percentile, falling back to the kind cohort; never a score floor or confidence evidence. MLH membership alone is not tier A.",
                      "Cohort priors shrink toward 45 with ten pseudo-observations; active source rows from the last 180 days set the cohorts.",
                      "Evidence below 30 means Not enough info. Confidence: high 70+, medium 40+, low below 40.",
                      "USDC/USDT count as USD. ECB rates are cached by the worker; static reference rates are the offline fallback.",
                      "Build-event totals use the published monotone calibration knots, fitted to the November 2026 crawl. Counts and cohort statistics change as source coverage changes."]}
