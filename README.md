# Hackfinder

Hackfinder is a free hackathon finder that collects listings from **91 sources**: hackathon platforms (Devpost, Devfolio, Unstop, MLH, DoraHacks, ...), general event sites (Luma, Meetup, Eventbrite), country hackathon sites (UK, US, Germany, India, ...) and organizer/university sites. It needs no login: "Upcoming hackathons" opens the list directly.

Features:
- **Hackfinder Score** (0-100, with the reasons shown): a transparent formula, not AI. See `/methodology`.
- **Near me**: hackathons within a radius of your location or a city you pick.
- Filters for region/country, topic, type (hackathon, game jam, CTF, ideathon, coding contest) and format. Talks and meetups are labelled, not mixed in.
- Duplicates listed on several sites are merged into one event, and events you can no longer join are removed.

It runs entirely on free plans (see [DEPLOY.md](DEPLOY.md)):
- **Website + read-only API**: Vercel Hobby (static files in `static/` and one FastAPI function).
- **Database**: Neon Postgres.
- **Crawler**: GitHub Actions on a public repository.

## How data flows
- The crawler (`python -m hackfinder.worker --pass quick|browser|full`) runs the collectors and writes to the database. The website never crawls.
- The page loads the latest data from the database when it opens; the **Refresh** button loads it again. There is no live stream and no polling.
- API responses are cached for 30 s in the function and 60 s on Vercel's CDN.

| Pass | Schedule (UTC) | Sources |
|---|---|---|
| `quick` | every 3 h at :17 | 42 fast sources: the main platforms, Luma's main searches, and NL/DE organizer sites |
| `browser` | every 6 h at :47 | sources that need a real browser: ETHGlobal, Kaggle, itch.io, Hackathon.com, lablab, DoraHacks, Encode Club, WeMakeDevs, AI Tinkerers |
| `full` | daily at 03:17 | every source and every scope, including Meetup, the country sites and Luma's full expansion |
| `local` | manual | Eventbrite and Global Game Jam, from your own computer (see below) |

The pass lists live in `PASSES` in `hackfinder/worker.py`; `full` runs every registered collector (`COLLECTOR_IDS` in `hackfinder/collectors/__init__.py`).

- **API sources** use httpx. **Scraped sources** use SeleniumBase CDP mode (`sb_cdp.Chrome`) with Playwright attached through `connect_over_cdp` (`hackfinder/browser.py`).
- Collectors page through each listing until its real end (safety limit: 100 pages). A collector may split its work into scopes (`scopes(pass_name)` + `collect_scope(scope)`); each scope is saved as soon as it finishes.
- **Luma** is crawled in depth in the full pass: after the searches it walks every calendar and organizer page it has found, then each event's own page (each step capped by `HF_LUMA_EXPAND_SECONDS`). If Luma refuses a request, that calendar is skipped after a short cool-down; three refusals in a row stop the step but keep what was found.
- **Lifecycle**: a listing becomes inactive only after 2 complete crawls in a row miss it. Failed, timed-out or suspicious (suddenly empty) crawls change nothing.
- **Cleanup**: after every crawl the merged `events` table is rebuilt, and anything not rebuilt is deleted, not hidden. That covers:
  - events whose date has passed;
  - events whose registration deadline has passed;
  - in-person or hybrid events that have already started (online submission windows stay until their end);
  - listings that disappeared from their source;
  - old copies of merged duplicates.
  Past rows are also deleted from `event_sources`.
- **Duplicates** (`dedupe.py`) are matched in two ways:
  - **By URL.**
  - **By fuzzy title and date.** These variations still count as the same event:
    - years and missing edition numbers ("Hoya Hacks" ~ "Hoya Hacks 2027");
    - up to a week of date drift for identical distinctive titles (aggregators often give the registration dates);
    - a venue name vs a city.
    Venues are compared by offline-geocoded distance, so the same title in two different cities stays two events. Different edition numbers or years never merge.
- **Geocoding**: locations are mapped to coordinates and countries offline (GeoNames), with a cached, rate-limited Nominatim fallback for unknown places.

## Run locally
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-worker.txt
.venv\Scripts\python scripts\import_cache.py
.venv\Scripts\python run.py
```
Then open http://127.0.0.1:8000. `import_cache.py` loads the old `data/cache.json`, if you have one. Google Chrome must be installed for the scraped sources.

Without `DATABASE_URL`, everything uses a local SQLite file, `data/hackfinder.db`. Set `DATABASE_URL` to use Postgres.

Crawl locally:
```powershell
.venv\Scripts\python -m hackfinder.worker --pass quick --only devpost,hackclub
```
```powershell
.venv\Scripts\python run.py --crawl quick
```

## API
- `GET /api/hackathons?kinds=hackathon,game_jam&format=online&q=ai&days=7|30|all&sort=start|prize|participants&order=asc|desc&page=1&per_page=100` (`per_page` up to 500). Returns `{events, total, page, per_page, updated_at, sources}`; each event has the `Event` fields plus `first_seen` and `last_seen`. The default sort is "starting soonest": events that haven't started yet by start date, then running events by end date, then events with an unknown date.
  More filters: `region=europe,...`, `country=NL,DE` (ISO codes), `min_score=60`, and `lat`/`lon`/`radius_km` for "near me".
- `GET /api/stats`: `{open_now, start_48h, new_this_week, total, sources, updated_at}`.
- `GET /api/sources`: per source `{id, name, method, status (ok|error|never), count, last_success_at, last_run_at, error}`.

## Layout
- `hackfinder/collectors/<id>.py`: one module per source. The contract is described in `collectors/__init__.py`.
- `classify.py`: sorts events by source first, then by multilingual keywords (see DECISIONS.md).
- `dedupe.py`: merges duplicates by URL, then by fuzzy title + date + place.
- `score.py`: the Hackfinder Score. `geo.py` / `geocoder.py`: offline and online geocoding.
- `db.py`: database access (Postgres via psycopg, or SQLite) and the schema: `events`, `event_sources`, `sources`, `scopes`, `crawl_runs`.
- `store.py`: display cleanup, per-source upserts, lifecycle rules, and rebuilding the merged `events` table.
- `worker.py`: the crawler passes.
- `app.py`: the read-only FastAPI app. It must not import collectors or scraping libraries.
- `static/`: landing page (`index.html`), list page (`hackathons.html`), near me (`near.html`) and score methodology (`methodology.html`). Add `?mock=1` to see the UI with sample data.
- `.github/workflows/crawl-*.yml`: the scheduled crawls. `vercel.json`, `.vercelignore` and `pyproject.toml`: the Vercel setup.

## Tests
Every `tests\test_*.py` file runs on its own with plain asserts and offline fixtures (no network):
```powershell
$env:PYTHONPATH='.'; $env:HF_GEOCODE_ONLINE='0'; Get-ChildItem tests\test_*.py | ForEach-Object { .venv\Scripts\python $_.FullName }
```
Live-check one collector:
```powershell
.venv\Scripts\python -m hackfinder.collectors._try devpost
```

## Env
- `DATABASE_URL`: Postgres connection string. Vercel uses the pooled URL; the crawler uses the direct URL. Unset = local SQLite.
- `HF_DB_PATH`: SQLite file (default `data/hackfinder.db`).
- `HF_DB_POOL_MAX` (2): Postgres connections per web instance. The worker always uses 1.
- `HF_API_CACHE_SECONDS` (30)
- `HF_PORT` (8000)
- `HF_MAX_BROWSERS` (3)
- `HF_HEADLESS` (1)
- `KAGGLE_USERNAME` / `KAGGLE_KEY`: optional; Kaggle uses its official API when they are set.
- `HF_LUMA_EXPAND_SECONDS` (900): time cap for each Luma expansion step (calendars, hosts, details).
- `HF_LUMA_COOLDOWN` (20): seconds to wait after Luma refuses a request.
- `HF_GEOCODE_ONLINE` (1): set to 0 to skip the Nominatim fallback. `HF_GEOCODE_MAX`: online lookups per run.

## Sources that block GitHub (local crawl)
Eventbrite (HTTP 405) and Global Game Jam (Cloudflare 403) refuse requests from GitHub Actions' datacenter IPs, even from a real Chrome window. They work from a home connection, so they're not part of the GitHub crawls (`LOCAL_ONLY` in `hackfinder/worker.py`). Instead they run from your own computer and write to the same Neon database:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\crawl_local.ps1
```
The first run asks for the direct Neon URL (input hidden) and saves it in `.env.local`, which git ignores. Run it manually whenever you want fresh Eventbrite/GGJ data. If it doesn't run, those two sources' events stay as they were until their end dates.

## Known gaps
- Meetup is scraped from keyword search and runs only in the daily full pass. Note: this ignores Meetup's robots.txt and conflicts with its terms of service.
- lablab.ai now redirects to Starfield Labs, which lists no events.
- Kaggle listings have no exact dates.
- Devpost dates are submission periods.
- Crawling from GitHub's servers makes blocks more likely (Meetup, Luma).
- Not collected: AngelHack (refuses automated requests), Bayern Innovativ (drops connections) and openhackathons.com (CAPTCHA).
