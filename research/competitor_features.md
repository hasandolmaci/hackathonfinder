# HackathonRadar competitor research (read-only)

Method: WebFetch of public pages (no signup, no forms), 2026-11-22. Fetches return text only, so some JS-rendered detail (table columns, filter options, the "Rank for me" UI) was not visible. Those gaps are marked "unverified". The screenshot supplied by the user fills a few of them.

## 1. Feature inventory

| Feature | How it works | Tier |
|---|---|---|
| Landing | Counters (open now, start in 48h, new this week, near you), "Starting soonest" card with Near me / Global toggle, featured events, browse by city / audience / topic, sponsor logos. Claims 16.7K tracked, 149 countries, 12.1K scored, 51-56 platforms (the page is inconsistent). | Free |
| Database (/database) | Table with Filters, Columns chooser, Export CSV, rows per page, pagination ("Page 1 of 7"). Presets: ongoing, upcoming week. Per the screenshot: list / calendar / board views. | Free, but only the next 7 days. Hidden-count banner ("431 more upcoming hackathons hidden") with an Upgrade link. |
| Event detail | Title, dates, format, category, prize, description, registration rules, tags like "Vibe-code friendly". Quality breakdown, judge accessibility, organizer contacts and audience estimate are locked. | Basic free, extras paid |
| Map / Near me | Globe map. Near me defaults to a city (Eindhoven), has a "Use my exact location" button, lists in-person and hybrid events nearest first, with counts. | Free, 7-day window |
| Discover / collections | Programmatic SEO pages: city, country, Europe, topic (/discover/c/ai), audience (students, beginner, vibe-code, with-prizes, online), month and year pages, "just found" (by ingestion date). | Free |
| Rank for me | Not documented on any public page (unverified). Docs only show a 0-1000 internal rank score in the API pipeline. Likely a personalised sort, probably account-based. | Unknown |
| Quality score | 0-100 per event (see section 2). | Number free, breakdown paid |
| Judge opportunities (/for-judges) | List of events seeking judges (191 seeking, 83 remote-friendly) with a 0-100 "judge accessibility" score and tags such as "organizer email available". | Browse free; alerts and organizer contacts are on Pro Plus |
| Sponsors / organizers directories | 183 sponsors, 10,051 organizers, with verified contacts for outreach. Page is empty ("Page 0 of 0") without upgrade. | Organizers: Pro Plus. Sponsors: Enterprise. |
| Hack Passport | Profile that tracks what you have built, with stamps and verification. | Free account |
| Alerts / saved searches / favorites | Email alerts for saved searches. | Dev Pro |
| Free tools | Six listing tools (score, price, time your hackathon), 3 runs per day with a free account. | Free account |
| Discord community and bot | Community plus a bot. | Free |
| API, MCP, webhooks, Sheets sync | REST API with a Bearer key (Enterprise only). MCP server that follows plan permissions. Webhooks for new events. Google Sheets sync. Inbound enrichment and suppression endpoints. openapi.yaml published. | Enterprise (Sheets: Pro Plus) |
| Insights (/state-of-hackathons) | Annual trend report: 2.8K events in 2025, projected 9.4K in 2026. Prize totals, participants, AI share about 67-69%, top countries, cities and organizers. | Free |
| Changelog (43 entries) | Monthly shipping log, used as marketing and SEO. | Free |
| Docs | Large docs site (API, MCP, judges, sponsors, passport). | Free |
| Compare pages | /compare/platforms/<devpost, devfolio, mlh, ...>, SEO against each source platform. | Free |
| Request a source / feature your hackathon | Intake forms, paid featured placement. | Paid placement |

Plans: Free, Dev Pro (full calendar, alerts, CSV), Pro Plus (organizer contacts, Sheets), Enterprise (sponsor dataset, API). No prices are published in the page text. Stripe billing.

## 2. Quality score (what is public)

- Source: /docs/sponsors/quality-scores, plus the landing page and the API docs.
- Scale 0-100. Tiers: green 70-100, amber 40-69, red 0-39.
- Five dimensions: Organiser (track record), Event Maturity (readiness), Sponsors (appeal), Participants (experience), Operations (listing quality).
- Output: total, per-dimension bars, short reasons (e.g. "Prize pool clearly stated"), and a "Missing data" line (e.g. "No judging criteria").
- Confidence label High / Medium / Low. The docs advise caution with "a high score with low confidence".
- The docs say the score rates the listing, not the event. Updates "within about a day".
- Landing example: overall 87 with sub-scores for prize credibility 92, organizer history 88, listing completeness 71, judging transparency 64. The landing page names different dimensions from the docs, which suggests the score was reworked.
- Weights, formula and per-dimension inputs are NOT published. Likely inputs, inferred: prize stated or verified, dead-link check, organizer's past event count, completeness of fields (judging criteria, sponsors, contacts), sponsor history.
- The score is also a sort and ranking signal (the docs mention a 0-1000 score step in the API pipeline).
- Judge accessibility is a separate 0-100 heuristic. Signals: organizer email present, judging mentioned, small or community event, online or hybrid, student-only (direction not stated). Tiers: 70-100 likely open, 40-69 worth reaching out, 0-39 probably closed. They call it "a heuristic" and say to verify.

## 3. Data fields they show that we lack

Hackfinder already has title, source, kind, format, dates, prize, participants, URL and location. Fields they show or sell that we lack:
- Sponsors (names and event counts). Likely from listing text and logos on Devpost, MLH and organizer pages, plus their own enrichment.
- Travel support column (screenshot). Likely parsed from descriptions or listing fields, or via LLM extraction. Few sources expose it natively.
- Organizer entity: name, history, event count, contact email (the paid moat). Likely from page scraping and enrichment.
- Judging info (judges, criteria, "seeking judges"), eligibility (student-only, age, beginner-friendly), tags or categories (AI, climate, fintech, vibe-code friendly), prize credibility, city and country geo-coding for pages and near-me, first-seen date, platform of listing.
- Participants per event: they have a column, as we do. We only have it where sources expose it.
- The sources they use are not listed publicly (a Request a source form exists). They claim 51+ platforms against our 15, and DoraHacks is one of them.

## 4. Better and worse than us

They do better:
- A quality score with reasons and a visible "missing data" line. We have none.
- Programmatic SEO pages: city, country, topic, month, year, compare. This drives traffic. We have two pages.
- Near me with city default plus exact location, counts, and a map or globe.
- Calendar and board views, a column chooser, saved searches, alerts and a Passport.
- Rich filter taxonomy (students, beginner, vibe-code, prizes, remote).
- Sponsor and organizer data, a judge-opportunity niche, an insights report, and a documented API, MCP and webhooks (paid).
- More sources (51+ against 15) and bigger claimed counts (about 16.7K tracked).
- Docs, a changelog and Discord, which build trust.

We do better:
- Free and unlimited. The free tier shows only 7 days and hides hundreds of upcoming events behind an Upgrade link. Our list has no paywall.
- No login. Their alerts, passport, tools and contacts need an account.
- CSV export is listed in the Dev Pro tier in the pricing text, but the screenshot shows an Export CSV button. Either way it is gated or limited. Ours is free.
- Our read-only API is public and free. Theirs requires Enterprise.
- Transparency: our README and DECISIONS.md state the lifecycle rules and known gaps. Their score weights and inputs are opaque and inconsistent (51 vs 56 platforms, differing dimension names).
- Their claimed counts look inflated and mixed: "open now" includes ongoing events, and an early-listing example showed a prize with a hidden condition. We show real end-of-listing totals.
- We offer filters by kind (game jam, CTF), which their hackathon-only framing may not.

## 5. Prioritized improvements for Hackfinder

| # | Improvement | Effort | Impact |
|---|---|---|---|
| 1 | Open "listing completeness" score (0-100) computed from fields we already hold (prize, dates, location, URL alive, participants, description length, source count). Show reasons and a "missing" line. Publish the formula. Never gate it. | M | High: matches their headline feature with transparency |
| 2 | Near me: IP or browser geolocation with a city fallback, radius filter, "N near you" counter on the landing page. Needs geocoding of locations in the crawler. | M | High |
| 3 | Add a tags / themes field (AI, climate, web3, students, beginner) by keyword rules extended from classify.py, then topic filter chips. | S-M | High |
| 4 | Static SEO pages generated from the API: /city/<x>, /topic/<x>, /month/<yyyy-mm>, /online. Free and indexable. | M | High (traffic) |
| 5 | Extract sponsors, travel support and eligibility (students-only) from descriptions of Devpost, MLH, Devfolio and Unstop. Rules first, optional LLM pass later. | M-L | Medium-High |
| 6 | Columns chooser and rows-per-page on the list, plus calendar view. Our API already supports per_page up to 500. | S-M | Medium |
| 7 | "Just added" sort and badge using first_seen (we already store it). | S | Medium |
| 8 | Judge opportunity filter and a simple "welcomes judges" heuristic. A niche they sell. | M | Medium |
| 9 | Public changelog and data-methodology page (sources, freshness, limits). | S | Medium (trust) |
| 10 | More sources (DoraHacks, Hackathon.com variants, regional platforms such as Unstop/Devfolio coverage, MLH regional). | L | Medium-High |
| 11 | Optional "Rank for me" via local preferences stored in the browser (no login): interests, location, format. | M | Medium |
| 12 | Add `.ics` / calendar subscription feed for a filtered query. They charge for alerts, so a free feed is a differentiator. | M | Medium |
| 13 | Advertise "free, no limits, no login, open API" prominently in the UI. | S | Medium |

Must stay free and no-login: list access, full export, the API, quality score and its reasons, near me, calendar feed, and any personalization (store it locally in the browser).

## Caveats
- Several fetched pages were cached or lagging (the event detail page was 12 days old). Counts differ between pages.
- "Rank for me", exact table columns and the filter set were not visible in fetched text. Confirm in the browser if needed.
- No branding or text was copied. Quotes are short.
