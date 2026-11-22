# Deploying Hackfinder for free

Everything here uses free plans:
- **GitHub** (public repository): stores the code and runs the crawler on a schedule (GitHub Actions).
- **Neon** (free Postgres): stores the hackathons.
- **Vercel Hobby**: serves the website and the read-only API.

The website never crawls. The crawler writes to Neon on a schedule, and the website reads from Neon.

You need about 30 minutes. You don't need a credit card.

## 1. Put the code on GitHub
1. Create an account at https://github.com/signup.
2. Click **+** (top right) → **New repository**.
   - Name: `hackfinder` (any name works).
   - Visibility: **Public**. GitHub Actions minutes are free and unlimited only for public repositories.
   - Don't add a README, .gitignore or license (the project already has them).
   - Click **Create repository**.
3. Install Git (https://git-scm.com/downloads) if you don't have it. In a terminal, in the project folder, run (replace `YOUR-NAME`):
   ```powershell
   git init
   git add .
   git commit -m "First version"
   git branch -M main
   git remote add origin https://github.com/YOUR-NAME/hackfinder.git
   git push -u origin main
   ```
   `.gitignore` keeps out `.venv/`, `data/` and local database files. Never commit a database URL or any other password.

## 2. Create the Vercel project and the Neon database
1. Create an account at https://vercel.com/signup. Choose **Continue with GitHub** and the **Hobby** plan.
2. Click **Add New…** → **Project**, then **Import** your `hackfinder` repository.
   - Framework preset: Vercel detects **FastAPI** from `pyproject.toml` (`[tool.vercel] entrypoint = "hackfinder.app:app"`). Leave the build settings empty.
   - Click **Deploy**. The first deployment works, but the API has no database yet, so the page shows "Data is temporarily unavailable". That's expected.
3. Open the project → **Storage** tab → **Create Database** → **Neon** (Serverless Postgres) → **Continue**.
   - Plan: **Free**. Region: **AWS Europe Central 1 (Frankfurt)**; `vercel.json` runs the website functions in Frankfurt (`fra1`) too, so they sit next to the database.
   - Connect it to your project for all environments (Production, Preview, Development).
   - Vercel now adds `DATABASE_URL` (the **pooled** URL; its host contains `-pooler`) and `DATABASE_URL_UNPOOLED` (the **direct** URL) to the project's environment variables.
4. Copy the direct URL for step 3: **Settings** → **Environment Variables** → `DATABASE_URL_UNPOOLED` → reveal and copy. It looks like `postgresql://user:password@ep-something.region.aws.neon.tech/neondb?sslmode=require`.
5. Redeploy so the website picks up `DATABASE_URL`: **Deployments** → the latest deployment → **⋯** → **Redeploy**.

Using Neon directly instead: sign up at https://neon.com, create a project, and open **Connect**. The connection string with **Connection pooling** turned on is the pooled URL; with it off, it's the direct URL. Then add the pooled one in Vercel as `DATABASE_URL` (**Settings** → **Environment Variables**) and redeploy.

## 3. Give the crawler the database URL
1. On GitHub, open your repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
2. Name: `DATABASE_URL`. Value: the **direct** URL from step 2.4. Click **Add secret**.
3. Optional (better Kaggle data): add `KAGGLE_USERNAME` and `KAGGLE_KEY` the same way. Get them from https://www.kaggle.com/settings → **API** → **Create New Token**.

Secrets are never shown in logs, even in a public repository.

## 4. Run the first crawl
1. In your repository, open the **Actions** tab. If GitHub asks, click **I understand my workflows, go ahead and enable them**.
2. Click **crawl-full** → **Run workflow** → **Run workflow**.
3. It takes 20–60 minutes. It creates the tables, crawls every source and fills the database. A red source in the log is fine: one failing source never stops the run.
4. Open your Vercel URL (e.g. `https://hackfinder-yourname.vercel.app`). The hackathons are there.

Want data immediately instead? From your own computer, with the project's virtual environment (see README.md), import the old local cache:
```powershell
$env:DATABASE_URL = "postgresql://...direct URL..."
.venv\Scripts\python scripts\import_cache.py
Remove-Item Env:DATABASE_URL
```

After this, the crawls run on their own:
| Workflow | When (UTC) | Sources |
|---|---|---|
| crawl-quick | every 3 hours at :17 | API sources, Luma's main searches |
| crawl-browser | every 6 hours at :47 | Chrome-scraped sources (ETHGlobal, Kaggle, itch.io, Hackathon.com, lablab) |
| crawl-full | daily at 03:17 | every source, every Luma search, Meetup |

## 5. Free-tier limits to watch
- **Vercel Hobby is for personal, non-commercial use only.** Ads, paid features or any business use need Vercel Pro ($20/month).
- **Neon free plan: 100 CU-hours of compute per month** (plus 0.5 GB of storage). The database sleeps when idle and wakes up for each crawl and for website visits that miss the CDN cache. Check usage in the Neon console (**Billing** / **Usage**). If you get close to the limit, run `crawl-quick` less often: edit the `cron:` line in `.github/workflows/crawl-quick.yml` (for example `17 */6 * * *`).
- **GitHub Actions schedules are best effort.** Runs can start minutes (sometimes an hour) late, or be skipped when GitHub is busy.
- **GitHub disables scheduled workflows after 60 days without repository activity.** Any commit re-enables them, or re-enable each workflow in the **Actions** tab when GitHub emails you.
- **Blocks from cloud servers.** Some sites (Meetup, Luma) may block GitHub's servers. The source then shows an error on the site; the other sources keep working.

## Optional: a read-only database user for the website
The website only reads. To make that a rule, create a read-only role in the Neon console (**Roles** → **New role**), then in the **SQL Editor** run (replace `web_reader`):
```sql
GRANT USAGE ON SCHEMA public TO web_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO web_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO web_reader;
```
Then put that role's **pooled** URL in Vercel's `DATABASE_URL` and redeploy. Keep the owner's direct URL in the GitHub secret, because the crawler writes.

## Troubleshooting
- **The site says "Data is temporarily unavailable"**: the tables don't exist yet (run **crawl-full** once) or `DATABASE_URL` is missing in Vercel (add it and redeploy). Vercel → project → **Logs** shows the error.
- **A workflow fails at "Check the DATABASE_URL secret"**: add the secret (step 3).
- **A workflow fails at "python -m hackfinder.worker"**: the database refused the connection. Check that the secret is the full URL, including `?sslmode=require`.
- **New events don't appear right away**: API responses are cached for up to a minute by Vercel's CDN, and the page shows data from the last crawl.
