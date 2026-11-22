# HackathonRadar: which platforms they read (researched 2026-11-22, read-only)

## How we found it
Their public /stats page ships the full source breakdown in its page payload (`totalSources: 55`, `hackathonsBySource`, `dataQualityBySource`, `sourceReliability`). That is a direct list of 55 ingestion keys with record counts. Marketing says "51 platforms"; their llms.txt says "40+". Counts below are all-time rows (16,657 total, includes past events), not upcoming. Last 30 days: 2,111 events. Other things checked: sitemap.xml (4,592 URLs, detail pages at /database/hackathon/{id}), robots.txt, llms.txt, openapi.yaml (fields `source`, `source_id`, `source_urls`, `excludeSources`). Their API and MCP need keys/OAuth, so we did not use them; use this only as a source checklist.

Observations: luma, devpost, unstop are 74% of rows (Luma alone 30%). "manual" (696) is hand-entered or partner-submitted. Several are aggregators (allhackathons, hackathonhub, hackathonparty, hackathonsuk, openhackathons, eventornado), so they overlap direct sources.

## Table of the 55 sources
Have = already one of our 15 collectors. Evidence for every row = /stats `hackathonsBySource` (count shown).

| Source key | URL | Have? | Count | Region / focus |
|---|---|---|---|---|
| luma | lu.ma / luma.com | YES | 4944 | Global, city communities |
| devpost | devpost.com | YES | 3941 | Global |
| unstop | unstop.com | YES | 3491 | India, competitions |
| allhackathons | allhackathons.com | NO | 839 | Global aggregator |
| manual | partner form (/feature-your-hackathon) | n/a | 696 | Mixed |
| dorahacks | dorahacks.io | NO | 627 | Web3 global, big prizes |
| eventbrite | eventbrite.com | NO | 573 | Global, noisy |
| devfolio | devfolio.co | YES | 319 | India/web3 |
| taikai | taikai.network | YES | 228 | Corporate/web3, EU |
| mlh | mlh.com | YES | 115 | Student, US/EU |
| devnovate | devnovate.co | NO | 97 | India, student |
| hackclub | hackathons.hackclub.com | YES | 87 | High school |
| builderbase | builderbase (site returns a 114-byte stub) | NO | 87 | Small builder events |
| hackerearth | hackerearth.com | YES | 53 | India/global |
| akindo | akindo.io | NO | 51 | Web3, Japan |
| kaggle | kaggle.com | YES | 48 | ML competitions |
| twohero | twohero.io (unreachable) | NO | 38 | Unknown |
| encodeclub | encode.club | NO | 36 | Web3/AI, UK |
| hackindia | hackindia.xyz | NO | 28 | India |
| commudle | commudle.com | NO | 27 | India communities |
| wemakedevs | wemakedevs.org | NO | 26 | India |
| eventornado | eventornado.com | NO | 25 | Aggregator |
| openhackathons | openhackathons.org | NO | 25 | Global |
| hackjunction | hackjunction.com | NO | 25 | Finland / Junction |
| hackquest | hackquest.io | NO | 24 | Web3 |
| zindi | zindi.africa | NO | 24 | Africa, data science |
| lablab | lablab.ai | YES | 23 | AI |
| hack2skill | hack2skill.com | NO | 22 | India, corporate |
| hackathoncom | hackathon.com | YES | 20 | Global |
| cerebralvalley | cerebralvalley.ai | NO | 19 | AI, SF (links to Luma) |
| hackathonsuk | hackathons.uk (unreachable) | NO | 18 | UK |
| hackathonparty | hackathonparty.com | NO | 13 | Aggregator |
| hackathonhub | hackathonhub.com | NO | 12 | Aggregator |
| raptors | raptors.dev | NO | 9 | Small |
| whereuelevate | whereuelevate.com | NO | 8 | Small |
| aitinkerers | aitinkerers.org | NO | 8 | AI meetups |
| colosseum | colosseum.org | NO | 4 | Solana |
| superteam | superteam.fun | NO | 4 | Solana regional |
| angelhack | angelhack.com (403 to bots) | NO | 3 | Global |
| hackbarna, hackculture, hackonvibe, hackrice, hackspain, shenicest, indehub, loops, stormhacks, dubhacks, hackmeridian, hackmty, sye, makefun, hackuk, circuitfeed | single-organizer event sites | NO | 1-3 each | Long tail (university/city hackathons); cover via aggregators, no collectors |

Ours but not in their 55: ethglobal, ctftime, itch.io, meetup. That is our extra coverage.

## Liveness and ingest check for sources we lack
Fetched 2026-11-22, a few requests each. Upcoming estimates are guesses from all-time counts and page content, not measured.

- Zindi: live. Public JSON `https://api.zindi.africa/v1/competitions` works with no key. It reports `total_count 527, open_count 10`, per_page 10, with start/end, reward, organization. Upcoming/open about 10-15. Effort S. This is the only API I confirmed returns real data.
- DoraHacks: live, but an AWS WAF "Human Verification" page blocks plain HTTP (405). Needs our SeleniumBase CDP browser, then read the listing or the XHR it calls. Est. 40-80 open/upcoming, large prizes. Effort M.
- Eventbrite: live. Search pages (`/d/online/hackathon/`, per-city) contain `__SERVER_DATA__` JSON. Noisy, needs a strict hackathon title filter. Est. 100-300 upcoming across cities. Effort M.
- allhackathons.com: live, server-rendered Django. List at /hackathons/ with links `/hackathon/<slug>/`. Plain HTML parse, paginated. Aggregator, so dedupe against Devpost/Unstop. Their quality score for it is low (54/100). Est. 100-300 upcoming. Effort S.
- Devnovate: live React SPA (empty shell, one JS bundle). Data comes from an XHR I could not find statically; open the browser network tab. Est. 15-30 upcoming. Effort S-M.
- Hack2skill: live (172 KB HTML), embedded JSON likely, not inspected. Est. 5-15. Effort S-M.
- HackQuest: live (333 KB, Next.js). Est. 5-15 web3. Effort M.
- Cerebral Valley: live; events page links to luma.com pages. Cheapest route is our Luma collector (add their calendar). Est. 5-10. Effort S.
- Commudle: live (64 KB), uses an unidentified API. Est. 5-15. Effort M.
- WeMakeDevs, Hack Junction, Superteam, Colosseum, AI Tinkerers, OpenHackathons, Eventornado, HackathonParty, HackIndia, Raptors, Whereuelevate: HTTP 200, not inspected further. Each est. under 15 upcoming. Effort M, low value.
- HackathonHub: live 2 KB SPA shell. Aggregator, skip.
- Not verified: akindo.io, hackathons.uk, twohero.io (no response from here); Builderbase (114-byte stub); AngelHack (403); Encode Club /events (404, find the right URL).

## Prioritized new sources (highest unique volume first)
1. Eventbrite (M): `__SERVER_DATA__` JSON by city + keyword filter. Biggest gap (573 rows for them). Needs a strict filter.
2. allhackathons.com (S): plain HTML, 839 rows for them. Mostly overlap, but the best long-tail source (small/university events).
3. DoraHacks (M): web3 flagship with big prizes; needs the CDP browser past the WAF.
4. Zindi (S): free public JSON API; unique Africa/data-science coverage.
5. Devnovate (S-M): India student; find the XHR endpoint in the network tab.
6. Hack2skill (S-M): India corporate hackathons.
7. Cerebral Valley (S): reuse the Luma collector.
8. HackQuest, Commudle, Hack Junction, Encode Club, Superteam, AI Tinkerers (M each): niche/regional.
9. From our SOURCES.md, not in their 55 (so a way to beat them; not checked in this pass): Global Game Jam, connpass (Japan), Agorize, BeMyApp, Junction-style regional lists.

Items 1-4 would close nearly all of the remaining gap by row count; the rest is long tail.

## Caveats
- Counts are all-time rows, not upcoming; real upcoming per source was not measured.
- Only Zindi's API was confirmed with real data. Other ingest methods are inferred from page fetches and need a browser network check before building.
- The source list comes from their own public stats page; no login or API use.
