# Architecture — XPND DRUDGE

This repository maintains **two editions** of the same product from one news pipeline.

| Edition | Path | Host | Freshness |
|---------|------|------|-----------|
| **Live (original)** | `app/` FastAPI | Local / Render / any PaaS | On-demand (news ~15m cache, payload ~60s) |
| **Static (Pages)** | `site/` | GitHub Pages | Hourly Actions snapshot |

Both share:

- Holdings CSV: `data/holdings.csv`
- Sentiment, junk filters, story grouping: `app/news.py`, `app/sentiment.py`
- Quotes + portfolio stats: `app/stocks.py`
- Brief / lead / trending / latest: `app/brief.py`
- **Payload contract:** `app/payload.py` → `build_dashboard_payload()`
- UI: `app/static/*` (copied into `site/static/` at build time)

```
        First Trust XPND holdings page
                           │
                scripts/update_holdings.py
                           │
              data/holdings.csv + holdings_meta.json
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
     app/payload.py              scripts/build_static_data.py
     (live request)              (hourly / workflow_dispatch)
              │                         │
              ▼                         ▼
     FastAPI /api/dashboard      site/data/dashboard.json
              │                         │
              ▼                         ▼
     Jinja dashboard.html        site/index.html
     + /static/*                 + site/static/* (synced)
              │                         │
              ▼                         ▼
         Live server              GitHub Pages SPA
```

## One rule (static edition)

**Never scrape RSS or Yahoo inside the browser or at page-request time on Pages.**
All fetching happens in `scripts/build_static_data.py` during GitHub Actions (or locally).
The deployed site only loads JSON/CSV.

This is the same architecture lesson documented in AI Drudge / Cyber Drudge.

## JSON contract

`dashboard.json` / `/api/dashboard` fields (selected):

| Field | Purpose |
|-------|---------|
| `mode` | `"live"` or `"static"` |
| `generatedAt` | ISO UTC build time |
| `quotesAsOf` | ISO UTC when quotes were fetched |
| `companies[]` | Per-holding articles + severity |
| `lead`, `brief`, `trending`, `latest` | Home rails (rule-based in `app/brief.py`, not an LLM) |
| `alerts[]` | Negative digest / CSV source |
| `stocks`, `portfolio` | Quotes + weighted day move |
| `coverage` | News + quote health: `missingNews`, `feedFailures`, `emptyFeeds`, `articleCount`, `quoteCoverage`, `quotesAsOf`, `quoteOutliers` |
| `sectors[]` | Filter dropdown |
| `holdingsSync` | Official-universe sync: as-of, added, removed, reconstitution flag |

`severe_total` counts `severity == "severe"` headlines and skips `low_value` filings.

Client config (`window.XPND_CONFIG`) switches data/CSV URLs and refresh UX.

## What differs by edition

| Capability | Live | Static |
|------------|------|--------|
| Instant re-fetch (`r` / ↻) | Yes — `POST /api/refresh` clears news + quotes | Reloads published JSON only |
| Trigger new scrape | Always | Actions → **Run workflow** |
| CSV export | `/api/alerts.csv` live | `data/alerts.csv` from last build |
| Hosting cost | Needs a Python process | Free GitHub Pages |
| Cold start | Free-tier hosts may sleep | None |
| Unit tests | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) on PR and `main` (app/tests/scripts; no scrape) | Same tests, plus scrape + quality gate + Pages deploy in `refresh-pages.yml` |

UI features (search, filters, bookmarks, mutes, theme, keyboard, severity, grouping) are identical — they run entirely in the browser against the payload.

Holdings sync runs in the Pages workflow (`scripts/update_holdings.py`, continue-on-error so an FT outage does not kill news). Names that leave the fund are deactivated and drop out of live news sections.

Static quality gate (hard fail; last-good `site/` stays published if the job dies before commit): `company_count` 40–60, `headline_count` ≥ 100, `quoteCoverage` ≥ 0.80 when `coverage` is present, and fail when `missingNews` > 10 **and** `missingNews / company_count` > 0.20. Missing `holdingsAsOf` is a warning unless `company_count` is also below 40.
