# Hackfinder vs HackathonRadar (2026-11-22)

Based on their live site (landing, /database, /discover), checked in a browser, plus research/competitor_features.md and research/competitor_sources.md. Our numbers are from https://hackathonfinder-taupe.vercel.app on the same day.

## 1. What we do better
| | Hackfinder | HackathonRadar |
|---|---|---|
| Access | Everything free, no login, no limit | Free list stops after 25 rows of the next 7 days ("432 more upcoming hackathons hidden, Upgrade") |
| Score | Open formula on /methodology; every event shows 5 bars, reasons, missing data and confidence | Formula not published; full breakdown is paid; landing and docs name different score dimensions |
| Event kinds | Hackathons, game jams (itch.io 437, Global Game Jam 96), CTFs (CTFtime), Kaggle/Zindi competitions, ideathons, with filters | Hackathons only |
| Sources they don't have | ETHGlobal, CTFtime, itch.io, Meetup, Global Game Jam | n/a |
| Near me | Browser location or typed city; location stays in the browser | Near me with a default city and a map |
| CSV export and API | Free, public, read-only | CSV in a paid tier; API, MCP and webhooks Enterprise only |
| Honest numbers | Real totals from our database | 1,027 "open now" on the landing vs 529 "upcoming" on /discover; 51 vs 56 platforms |

## 2. What they do better
- **Volume:** 56 platforms and 16.7K events tracked, plus 696 hand-submitted listings. They show about 1,027 open versus our 665 hackathons (plus jams, CTFs and competitions).
- **Discovery / SEO pages:** by type (student, beginner-friendly, vibe-code, cash prizes, travel covered, online, in-person, this week, weekend, newly added), by month, by region, by 25 categories (AI, Web3, Fintech, Health, Climate, Gaming, Cybersecurity, ...) and by city (60+ with counts).
- **Themes/categories** on every event. Our tags exist but aren't shown or filterable.
- **Personalisation:** "Tell us what you're into" interest chips (AI agents, Climate, Fintech, Web3, Robotics, Health, Devtools, Games) and a "Rank for me" button.
- **Map / globe** view of every event.
- **Ecosystem:** sponsor and organizer directories (sponsor logos and event counts on the landing page), judge opportunities, Discord and a bot, Hack Passport, blog, changelog, stats and an annual "State of Hackathons" report, free tools.
- **Developer products:** API docs, MCP server, webhooks, agent skills (all paid).
- **Table tools:** column chooser, calendar/board views, Participants sort, Sponsors and Travel Support columns. Those two columns were almost all empty in practice.
- **Submit / feature your hackathon** form.

## 3. What we can do (free, no login)
| # | Improvement | Effort | Impact |
|---|---|---|---|
| 1 | Categories/themes for every event (keyword taxonomy of ~20 categories from title, description, tags, themes), category chips and filter | S | High |
| 2 | Type filters from the signals we already have: student, beginner-friendly, cash prize, travel covered, weekend, newly added | S | High |
| 3 | Interest picker on the landing page (saved only in the browser) that personalises the order: score + interest match | S | Medium |
| 4 | Event detail pages (/h/<slug>): score breakdown, every source listing it, map, add to calendar, similar events | M | High (SEO + sharing) |
| 5 | SEO pages + sitemap.xml + meta tags: /in/<city>, /category/<topic>, /month/<yyyy-mm>, /type/<student...> | M | High (traffic) |
| 6 | Map view (Leaflet + free OpenStreetMap tiles) using the lat/lon we already store | M | Medium |
| 7 | Free alerts without accounts: RSS and .ics calendar feeds for any filter | M | Medium |
| 8 | "Submit a hackathon" via a GitHub issue form (free moderation queue) feeding a manual source | M | Medium |
| 9 | Stats page from our own database (counts by kind, country, prize, month) | M | Low-Medium |
| 10 | API docs page (our API is already free) | S | Low-Medium |
| — | Skip for now: Hack Passport, judge marketplace, paid placements, sponsor/organizer contact data | — | — |
