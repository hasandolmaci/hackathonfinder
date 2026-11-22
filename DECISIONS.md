# Decisions

## 1. What we ingest and show (2026-11-22)

**Decision:** collect broadly, store a small hackathon-focused set of categories, and show only hackathons by default.
We do not keep a full taxonomy of all events, and we do not throw away everything that isn't a hackathon at scrape time.

Reviewed by Claude Opus 5.5 and Codex GPT-6-Astra. Both reached this recommendation independently. (Fable 5.2 was unavailable because it requires usage credits.)

### Categories: one primary `kind` per event
| kind | Meaning | Shown by default |
|---|---|---|
| `hackathon` | A time-boxed event where people build a project or prototype. Includes buildathons, datathons and "AI build days". | yes |
| `game_jam` | itch.io, Global Game Jam, Ludum Dare | opt-in filter |
| `ctf` | Capture-the-flag security competitions (CTFtime etc.) | opt-in filter |
| `coding_competition` | Kaggle, algorithm or leaderboard challenges, long prize challenges | opt-in filter |
| `ideathon` | Pitch or idea events with no required build | opt-in filter |
| `other` | Talks, workshops, meetups, conferences | never shown; stored for a limited time |
| `unknown` | Not enough information to decide | review queue, never shown |

Separate attributes (not categories): `format` (online / in-person / hybrid), `audience` (student, high-school, open), `domain` (AI, web3, gov/civic, hardware...), `confidence`, `classified_by` (source / keyword / llm / manual).

### Pipeline
1. **Find events.** Hackathon-specific sites: take everything. General event platforms (Luma, Eventbrite, Meetup...): narrow down using organizer calendars, site categories and keywords in several languages (hackathon, hack, jam, buildathon, CTF, ideathon, ハッカソン, 해커톤...).
2. **Keep the raw evidence.** Store source URL, source ID, the fetched text and fetch time. Keep rejected events for 30–90 days, with the reason they were rejected, so we can re-classify them without scraping again.
3. **Normalize, then classify.** Use three tiers:
   - The source decides (e.g. everything from Devpost or CTFtime).
   - Keyword rules.
   - An LLM, only for ambiguous events. Low-confidence results go to a review queue.
4. **Dedupe and publish.** Match on the registration URL, then on title + organizer + dates + city. Prefer the organizer's own platform. Keep yearly and local editions of the same event as separate events.

### MVP
- Start with about 10–15 accessible, productive sources: the main hackathon platforms, API/iCal feeds, and a small sample of Luma/Meetup.
- Classify with the source and keywords only. Add the LLM tier later.
- Include the full `kind` set in the schema from the start, but show only `hackathon` at first.
- Leave the bot-blocked sites for later.

### Risks to watch
- Keywords miss events with unfamiliar names, like "AI Build Night" or titles in other languages.
- False positives: a workshop *about* a hackathon is not a hackathon.
- Aggregators repeat each other's errors.
- Dedupe that is too aggressive merges different editions of the same event.
- Check samples of both accepted and rejected events.

## 2. Complete coverage without losing speed (2026-11-22)

**Decision:**
- Visitors are served from a SQLite database instantly.
- A background crawler keeps the database complete and fresh.
- Collectors stop at the real end of each listing, not at a fixed cap.
- Visiting a page no longer triggers a crawl.

Reviewed by Claude Opus 5.5 and Codex GPT-6-Astra; both recommended this independently. (Fable 5.2 was unavailable because it requires usage credits.)

### Where they differed, and what we chose
| Question | Opus | Astra | Decision |
|---|---|---|---|
| Where the crawler runs | Separate worker process | Scheduler inside the FastAPI process | **Separate process, started by `run.py`.** It's still one command, but a Chrome hang or crash can't take the website down. |
| Event storage | One `events` table | Merged `events` + `event_sources` (one row per source listing) | **Two tables.** This keeps track of which source said what, so an event disappearing from one source doesn't delete it. |
| Collector interface | `collect()` yields batches, plus optional scopes | Per-scope/page tasks with checkpoints; a generator alone can't resume | **Scope tasks with checkpoints.** `collect()` stays as a wrapper so small collectors keep working. |

### Storage (SQLite, WAL mode, file outside OneDrive)
- `events`: the merged event shown in the UI (fields from `models.Event`, plus `first_seen`, `last_seen`, `status` active/missing/expired).
- `event_sources`: one row per source listing, unique on (source, source_id) with URL as fallback. Holds raw JSON, a content hash, first and last seen, and a miss count.
- `sources`: cadence, last success, last error, `backoff_until` (circuit breaker).
- `scopes`: a source's search unit (e.g. `luma:place=amsterdam:q=hackathon`). Holds last crawled, last result count, a saturated flag, a checkpoint, and ETag/Last-Modified.
- `crawl_runs`: source, scope, start and finish, status, pages, rows, and `exhaustive` (true/false).

### Crawling
- **Hot pass:**
  - Cheap APIs every 15–30 min.
  - Browser sources hourly.
  - New listings and events starting soon come first.
- **Deep pass:**
  - Daily: full pagination, every Luma city page × several queries, more Meetup locations.
  - Expensive location rotations spread over 24–72 h.
- **Saving progress:** every page is written to the database as it arrives, with a checkpoint. An interrupted run resumes and is never marked complete.
- **When to stop:**
  - Stop on an explicit last page or cursor, an empty page, the total count reached, or a page with no new IDs.
  - Repeated pages mean paging has stalled; that is not success.
  - Keep a safety limit of 100 pages per scope, and log a warning if it is hit.
- **Politeness:**
  - At most 1–2 requests at a time per host, with a 1–2 s gap and some randomness.
  - Respect `Retry-After`, back off exponentially on 429/403/5xx, and stop when blocked.
  - Use conditional requests (ETag/If-Modified-Since) where supported.
  - At most 3 browsers in total.

### Per source
- **Luma:**
  - Search every Luma city page (87) with several queries (hackathon, hack, buildathon, datathon, game jam).
  - Add "hackathon <city>" searches for cities without a Luma page.
  - Add global and online searches.
  - Treat a search that returns exactly 50 results as saturated, and split it only with filters verified to work.
  - Dedupe by `api_id`.
  - Follow the public calendars of organizers who have posted hackathons, to find events Luma's search doesn't list.
  - Even this cannot prove we have everything.
- **Paginated APIs** (Devpost, Unstop, Devfolio, TAIKAI, Kaggle, itch.io): page until the end. CTFtime: split saturated time windows.
- **Meetup:** scroll until two scrolls in a row bring nothing new, and use many more locations. Deep pass only.
- **New sources are still needed** (Eventbrite, Global Game Jam, organizer sites). Paging further through existing sources can't recover events that aren't on them.

### Event lifecycle
- Events past their end date leave the upcoming list.
- A source listing becomes inactive only after two complete crawls in a row miss it, plus a grace period. Not being found in a ranked search isn't enough.
- Failed or partial crawls never hide an event.
- Stale but valid events stay visible with their "last seen" time.

### What visitors see
- `/api/hackathons` queries the database and responds in milliseconds.
- The SSE stream sends changes saved by the crawler.
- The UI shows "updated X min ago" per source.
- Wording: "continuously updated from live sources", not "fetched now".

### Migration order
1. SQLite + upserts; the API reads from the database; import the current cache.
2. Worker process + scheduler + checkpoints.
3. Remove caps one source at a time, Luma first.
4. Lifecycle rules.
5. New sources.

### Risks
- **Blocks:** 10× more calls to undocumented endpoints (Luma, Unstop, Devfolio) could get us blocked.
- **Meetup:** terms of service and robots.txt.
- **Long crawls:** deep crawls take 15–40+ minutes.
- **Windows machine:** sleep, reboots and leftover Chrome processes.
- **Freshness:** new local Luma events may take up to about 24 h to appear.

## 3. Deploying on Vercel (2026-11-22)

The user's requirement: the site must deploy to Vercel without complications. This changes decision 2: there is no long-running server process and no local SQLite file. Reviewed by Claude Opus 5.5 and Codex GPT-6-Astra, both of whom checked Vercel's documentation on 2026-11-22.

### Vercel facts that drive the design
- Python/FastAPI is supported natively; no rewrite is needed.
- Functions time out after 300 s on Hobby and 800 s on Pro.
- The filesystem is read-only apart from a temporary `/tmp`, so local SQLite is out.
- Cron on Hobby runs at most once a day (the newer Schedules beta allows every 15 min). Pro allows every minute.
- SSE streams are cut at the function time limit, and each open stream costs memory per visitor. Vercel recommends polling for updates that can be a few seconds late.
- Chrome inside Python functions isn't supported. Vercel's documented headless-browser path is Node-only, so SeleniumBase can't run in a function.
- The Hobby plan is personal and non-commercial only. Pro is $20/month.

### Decision
| Part | Choice |
|---|---|
| Frontend | The static files in `static/`, served from Vercel's CDN. |
| API | The existing FastAPI app as one Vercel Python function. **Read-only**: it only queries the database, with CDN caching (`s-maxage=60, stale-while-revalidate=300`). No crawling in requests or at startup. |
| Updates in the browser | **No automatic updates** (user decision 2026-11-22: new hackathons don't appear every 30 s). The page loads the latest data from the database when it opens, and a **Refresh** button reloads it. No SSE, no polling, no `/api/changes`. Each source shows "updated X min ago". |
| Database | **Neon Postgres** through the Vercel Marketplace, which injects `DATABASE_URL`. The schema is decision 2's five tables, using JSONB for raw data and `ON CONFLICT` upserts. |
| Crawler | **Outside Vercel**: the same Python worker code (`hackfinder/worker.py`, with scope tasks and checkpoints) writes directly to Neon. SeleniumBase CDP + `connect_over_cdp` runs unchanged, because the worker's machine has Chrome. |
| Where the worker runs | See "Open choice" below. |
| Packaging | Two requirements files: `requirements.txt` (web: fastapi, pydantic, psycopg) and `requirements-worker.txt` (adds httpx, selectolax, seleniumbase, playwright). The web app must not import any collectors. Exclude `tests/`, `data/` and `.venv/` from the Vercel bundle. |
| Secrets | Vercel gets a pooled, read-only `DATABASE_URL`. The worker gets a write-access database URL plus the Kaggle keys. |

### Where they agreed
- Vercel for the frontend and a read-only API.
- Neon Postgres.
- Polling instead of SSE.
- The crawler outside Vercel functions.
- Don't run crawling in chunks inside Vercel functions: it can't run Chrome, and it would split the crawler across two places.
- A remote browser service (Browserless/Browserbase) would replace SeleniumBase's own Chrome launch, so it doesn't meet the SeleniumBase CDP requirement.

### Open choice: where the worker runs
| Option | Cost | Pros | Cons |
|---|---|---|---|
| **A. GitHub Actions** scheduled workflows: hot every 20–30 min, browser hourly, deep daily (Opus) | **$0** if the repo is **public**. A private repo needs about 4,000+ min/month, over the 2,000 free. | Chrome is preinstalled; no server to look after. | Runs can be delayed or dropped; minimum interval 5 min; disabled after 60 days without activity; the code must be public. |
| **B. Small always-on Docker container** on Render, Railway or Fly (Astra) | About $5–25/month | Reliable timing; the repo can stay private; runs the decision 2 scheduler as is. | Paid; a server to look after. |
| **C. Vercel Daemon**: Docker container on Vercel (beta) | Pro plan + usage | Everything on Vercel. | Beta; Hobby quota runs out in about 9 days of running non-stop. |

The worker is written the same way for all three, so we can move between them later: start on A or B, then move to C on Pro if wanted.

### Migration order
1. `db.py` + Postgres schema; import `data/cache.json`.
2. Make the API read-only and switch the frontend from SSE to polling.
3. Deploy to Vercel with Neon.
4. `worker.py` (scope tasks, checkpoints) + the chosen worker host.
5. Remove caps one source at a time, Luma first.
6. Lifecycle rules.
7. New sources (Eventbrite, Global Game Jam, ...).

### Risks
- **Blocks from cloud servers:** crawling from a datacenter address (GitHub/Render) makes blocks more likely, especially Meetup and Luma.
- **Neon free-plan limits:** frequent crawls may use up the free compute allowance, so the cadence may need widening.
- **Beta features:** Daemons and Schedules are beta.
- **Commercial use:** any monetisation requires Vercel Pro.
