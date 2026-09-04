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
| `companies[]` | Per-holding articles + severity |
| `lead`, `brief`, `trending`, `latest` | Home rails |
| `alerts[]` | Negative digest / CSV source |
| `stocks`, `portfolio` | Quotes + weighted day move |
| `sectors[]` | Filter dropdown |
| `holdingsSync` | Official-universe sync: as-of, added, removed, reconstitution flag |

Client config (`window.XPND_CONFIG`) switches data/CSV URLs and refresh UX.

## What differs by edition

| Capability | Live | Static |
|------------|------|--------|
| Instant re-fetch (`r` / ↻) | Yes — clears server cache | Reloads published JSON only |
| Trigger new scrape | Always | Actions → **Run workflow** |
| CSV export | `/api/alerts.csv` live | `data/alerts.csv` from last build |
| Hosting cost | Needs a Python process | Free GitHub Pages |
| Cold start | Free-tier hosts may sleep | None |

UI features (search, filters, bookmarks, mutes, theme, keyboard, severity, grouping) are identical — they run entirely in the browser against the payload.
