# Live edition (original FastAPI server)

**Status:** maintained · source of truth for request-time APIs  
**Entry:** `app/main.py`  
**UI template:** `app/templates/dashboard.html`  
**Assets:** `app/static/`

## When to use this

- You need **on-demand** headline refresh during market hours
- You want API endpoints for other tools (`/api/dashboard`, `/api/holdings`, `/api/alerts.csv`)
- You are running locally on a desk / always-on host

## Quick start

```bash
./run.sh
# → http://127.0.0.1:8000
```

Or:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Cloud deploy (Render / Railway / etc.)

`Procfile` and `runtime.txt` are included:

```
web: uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Connect this GitHub repo as a **Web Service**, build with `pip install -r requirements.txt`, start via Procfile. Set `ENV=production` (or `XPND_DISABLE_DOCS=1`) so `/docs` and `/redoc` are off.

## Update holdings

```bash
.venv/bin/python scripts/update_holdings.py
```

Scrapes the official First Trust XPND holdings page into `data/holdings.csv` and writes `data/holdings_meta.json` (adds/drops, as-of date). Names that left the fund are deactivated so they stop appearing as live news sections. User-deactivated names that are still in the fund stay off. Use `--check` to report drift without writing, or `--keep-unlisted` only if you intentionally want extra watchlist tickers.

## Key modules

| Module | Role |
|--------|------|
| `app/payload.py` | Shared dashboard assembly (also used by static build) |
| `app/news.py` | Google News RSS, grouping, junk/low-value filters |
| `app/sentiment.py` | Negative scoring + severity tiers |
| `app/stocks.py` | Yahoo quotes + portfolio stats |
| `app/brief.py` | Lead, brief, trending, latest |

## Caches

- News feed cache: ~15 minutes (see `app/news.py`)
- Assembled payload: 60 seconds (`PAYLOAD_CACHE_SECONDS`)
- Quotes: ~10 minutes (`app/stocks.py`)
- `POST /api/refresh` or `?refresh=true` clears **news + quotes** (and the assembled payload)

## OpenAPI docs

`/docs` and `/redoc` stay enabled locally. They are turned off when `ENV=production` or `XPND_DISABLE_DOCS=1`. `/api/refresh` notes `docs: disabled` in that case.

## CI

Pull requests and pushes to `main` that touch `app/**`, `tests/**`, or `scripts/**` run unit tests via [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) (Python 3.12, no scrape, no Pages deploy). Failures are hard-fail.

## Do not remove

Keeping this edition means portfolio managers can always run a full live desk without waiting for the hourly Pages cron. Changes to scoring/filters should land in shared `app/*` modules so the static build picks them up automatically.
