# MVP sources (15)

Chosen against the MVP rules in DECISIONS.md:
- the site is reachable (all returned HTTP 200 on 2026-11-22),
- it lists many events,
- together the sources cover every `kind`,
- a small sample of general event platforms is included,
- no bot-blocked sites.

The "how to ingest" column is the *expected* method. It has not been checked against live data yet.

| # | Source | URL | Default `kind` | How we classify | Expected ingest | Why it's in |
|---|---|---|---|---|---|---|
| 1 | Devpost | https://devpost.com/hackathons | hackathon | source decides | JSON endpoint that powers the listing page | Largest global hackathon listing (online + in-person) |
| 2 | Major League Hacking (MLH) | https://www.mlh.com/seasons/2027/events | hackathon | source decides | scrape a static season page | Main student hackathon league (US/EU/global) |
| 3 | Devfolio | https://devfolio.co/hackathons | hackathon | source decides | scrape / site's JSON | Big in India and web3 |
| 4 | Unstop | https://unstop.com/hackathons | hackathon (+ ideathon / coding competition) | source + keywords | site's JSON search | Highest volume in India; mixes in competitions, so it tests our classifier |
| 5 | Hack Club Hackathons | https://hackathons.hackclub.com | hackathon | source decides | open-source public API | Easy win: high-school and student events with a clean API |
| 6 | TAIKAI | https://taikai.network/en/hackathons | hackathon | source decides | scrape | Corporate and web3 hackathons, strong in Europe |
| 7 | HackerEarth | https://www.hackerearth.com/challenges/hackathon/ | hackathon (+ coding competition) | source + keywords | scrape | Corporate hackathons and coding challenges |
| 8 | Hackathon.com | https://www.hackathon.com | hackathon | source decides | scrape | Global aggregator, good for testing dedupe against the others |
| 9 | ETHGlobal | https://ethglobal.com/events | hackathon (domain: web3) | source decides | scrape | Biggest web3 hackathon series (DoraHacks is bot-blocked, so it waits) |
| 10 | lablab.ai | https://lablab.ai/event | hackathon (domain: AI) | source decides | scrape | Main source for AI hackathons |
| 11 | Kaggle | https://www.kaggle.com/competitions | coding_competition | source decides | official API (free key) | Covers the `coding_competition` kind |
| 12 | CTFtime | https://ctftime.org/event/list/ | ctf | source decides | official public API | Covers `ctf`, clean API |
| 13 | itch.io Jams | https://itch.io/jams | game_jam | source decides | scrape | Covers `game_jam`, very high volume |
| 14 | Luma | https://luma.com/discover | mixed | keywords (+ LLM later) | scrape search/city/calendar pages | Sample general platform; many AI/startup hackathons are only posted here |
| 15 | Meetup | https://www.meetup.com/find/?keywords=hackathon | mixed | keywords (+ LLM later) | scrape keyword search | Second general platform sample; local community hack nights |

## Left out for now (and why)
- **DoraHacks, connpass, AngelHack, Global Game Jam:** they block plain requests, so they need browser scraping. Phase 2.
- **Eventbrite, Partiful, GDG, Microsoft Reactor, AWS:** they overlap heavily with Luma and Meetup and have low hackathon density. Phase 2.
- **Regional sites (48):** add them by target market after the MVP. Possible first picks: Coderspace (Turkey), German Hackathons, Japan Hackathons/connpass, DACON (Korea).
- **Small aggregators (Hacko, DevSafar, Yat's List, Hackathon Radar...):** they mostly copy Devpost, Devfolio and Unstop. They are useful later for checking that we aren't missing events, not as primary sources.

## Next check before building
For each source, confirm three things:
- how many current events it returns,
- that the expected ingest method works,
- what its robots.txt and terms say about automated access.
