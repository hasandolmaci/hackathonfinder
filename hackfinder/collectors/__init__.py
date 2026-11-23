"""Collector registry.

Each collector is a module `hackfinder/collectors/<id>.py` that defines:

    SOURCE = {
        "id": "devpost",                 # == module name
        "name": "Devpost",
        "url": "https://devpost.com/hackathons",
        "method": "api" | "scrape",      # api = public JSON/iCal/HTTP; scrape = hackfinder.browser.cdp_page
        "default_kind": "hackathon" | "game_jam" | "ctf" | "coding_competition" | "mixed",
    }

    def collect() -> list[Event]:
        '''Fetch LIVE upcoming/open events from the source. Synchronous; runs in a thread.
        Return [] (not raise) when there is simply nothing, and raise an exception on
        real failures (the worker records it per source). No time limit beyond the
        worker's own; it runs in GitHub Actions, never on the website.'''

A module MAY also define scopes (the worker then crawls scope by scope, upserts after
each one, and records it in the `scopes` / `crawl_runs` tables):

    def scopes(pass_name: str) -> list[str]:
        '''pass_name is "quick", "browser" or "full". Return a few high-value scopes for
        "quick" and all of them for "full", e.g. ["global:hackathon", "place:sf:hackathon"].'''

    def collect_scope(scope: str) -> list[Event]:
        '''Fetch one scope returned by scopes(). Raise on failure; the worker moves on.'''

collect() must still work on its own and covers every scope of the "full" pass.

Rules for collectors:
- API collectors use httpx (timeout <= 20 s) with a descriptive User-Agent; no browser.
- Scraping collectors use ONLY `hackfinder.browser.cdp_page()` (SeleniumBase CDP + Playwright connect_over_cdp).
- Only upcoming / currently-open events. No artificial caps (no [:200], no fixed page
  counts): paginate until the source is exhausted - an empty page, the last page or total
  reached, a page with no new IDs (stalled), or a past-only page of a date-sorted list.
  Keep a safety limit of 100 pages per listing/scope and log a warning when it is hit.
- Set Event.kind from the source when the source is unambiguous (confidence 0.9,
  classified_by="source"); for "mixed" sources leave kind="unknown" for classify.py.
- Be polite: no login, no CAPTCHA solving. Sources that need many requests (Luma) space
  them per host with jitter (_vertical_util.polite_json), back off on 429/5xx honoring
  Retry-After, and raise RuntimeError("blocked: ...") on a hard block.
"""
from __future__ import annotations

import importlib
from types import ModuleType

COLLECTOR_IDS = [
    # hackathon platforms
    "devpost", "mlh", "devfolio", "unstop", "hackclub", "taikai", "hackerearth", "hackathoncom",
    "allhackathons", "devnovate", "hack2skill", "commudle", "hackjunction", "wemakedevs",
    # verticals
    "ethglobal", "lablab", "kaggle", "ctftime", "itchio", "zindi", "globalgamejam",
    "dorahacks", "hackquest", "encodeclub",
    # general event platforms
    "luma", "meetup", "eventbrite",
    # regional
    "netherlandshackathons",
    # added 2026-11-23: organizer/university sites and country aggregators
    "aanmelder", "argentinahackathons", "austriahackathons", "brainport", "canadahackathons", "colombiahackathons", "eurodefense", "eventornado", "francehackathons", "germanhackathons", "hackathonhongkong", "hackathonparty", "hackathonsaustralia", "hackathonsingapore", "hackatum", "indiahackathons", "indonesiahackathons", "italyhackathons", "japanhackathons", "koreahackathons", "mexicohackathons", "nzhackathons", "pakistanhackathons", "spainhackathons", "starthack", "startupamsterdam", "swedenhackathons", "taiwanhackathons", "techeurope", "thailandhackathons", "tudelft", "turkeyhackathons", "ukhackathons", "ushackathons", "vietnamhackathons", "vu", "yesdelft", "zukunftgesundheit",
    # added 2026-11-23 (group C): more platforms and single-organizer sites
    "aitinkerers", "builderbase", "circuitfeed", "colosseum", "dubhacks", "govtechnl", "hackbarna", "hackculture", "hackindia", "hackmeridian", "hackmty", "hackonvibe", "hackrice", "hackspain", "hackuk", "indehub", "loops", "makefun", "raptors", "shenicest", "stormhacks", "superteam", "sye", "twohero", "whereuelevate",
]


def load_collectors() -> dict[str, ModuleType]:
    mods: dict[str, ModuleType] = {}
    for cid in COLLECTOR_IDS:
        try:
            mods[cid] = importlib.import_module(f"hackfinder.collectors.{cid}")
        except ModuleNotFoundError:
            continue  # not built yet
    return mods
