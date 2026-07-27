# XPND DRUDGE

Drudge-style portfolio news dashboard for the **First Trust Expanded Technology ETF (XPND)**.

Built for portfolio managers: recent headlines first, negative/risk news highlighted, one section per holding. UI patterns borrowed from [AI Drudge](https://pnelsonftp.github.io/ai-drudge/) and [Cyber Drudge](https://pnelsonftp.github.io/cyber-drudge/).

This repo maintains **two editions** from one shared pipeline:

| Edition | URL / how to run | Docs |
|---------|------------------|------|
| **Static (GitHub Pages)** | https://pnelsonftp.github.io/xpnd-drudge/ | [docs/STATIC.md](docs/STATIC.md) |
| **Live (FastAPI, original)** | `./run.sh` → http://127.0.0.1:8000 | [docs/LIVE.md](docs/LIVE.md) |

Architecture overview: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Why both?

- **Static** matches AI/Cyber Drudge: free Pages hosting, hourly Actions refresh, no live scrape in the request path (avoids OOM / rate-limit failures).
- **Live** keeps on-demand refresh and JSON/CSV APIs for a desk workflow.

Product features (search, filters, severity, bookmarks, mutes, FT theme, etc.) are the same. The only intentional difference is freshness mechanics — see the docs table in [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start — live server

```bash
./run.sh
# or
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Quick start — static site locally

```bash
source .venv/bin/activate
python scripts/build_static_data.py
cd site && python3 -m http.server 8088
```

Open [http://127.0.0.1:8088](http://127.0.0.1:8088).

Production static deploys hourly via [.github/workflows/refresh-pages.yml](.github/workflows/refresh-pages.yml). Manual rebuild: **Actions → Refresh static site and deploy Pages → Run workflow**.

## Deploy live server (optional)

This is a FastAPI app. Easiest free host is [Render](https://render.com):

1. New → Web Service → connect this GitHub repo
2. Runtime: Python · Build: `pip install -r requirements.txt` · Start: `Procfile`
3. Public URL will look like `https://xpnd-drudge.onrender.com`

## Features

| Feature | Notes |
|---------|--------|
| Company sections | One block per holding with live price chip and weight |
| Severity tiers | `NEG` (elevated) and `SEVERE` badges |
| Risk Radar | Portfolio-wide negative headlines, newest first |
| Daily Brief | Curated summary of risk + freshest items |
| Lead Story | Highest-impact recent headline with "also covered by" |
| Latest | Reverse-chronological across the book, grouped by day |
| Portfolio summary bar | Weight-adjusted day move, gainers/losers, headline counts |
| Jump index | Ticker chips with negative counts; click to scroll |
| Stock ticker | All holdings via Yahoo Finance |
| Story grouping | Duplicate coverage collapses into `+N src` |
| Noise filtering | Option chains dropped, 13F chatter demoted |
| Sort / filters / search | Weight, newest, negative, mover, A–Z; neg / 24h / unread / sector |
| ★ Bookmarks / ⏷ Read later | Persisted in `localStorage` with snapshots |
| Mute company or source | Manage via ✕ panel |
| Copy digest / CSV | Clipboard risk digest and alerts CSV |
| First Trust theme | Brand palette by default, navy night mode via `t` |
| Keyboard shortcuts | `/ r t n h u b l d c g ?` — press `?` |

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `/` | focus search |
| `r` | refresh (live scrape) / reload snapshot (static) |
| `t` | toggle dark / light |
| `n` | negative only |
| `h` | last 24 hours |
| `u` | unread only |
| `b` / `l` | bookmarks / read-later |
| `d` | copy risk digest |
| `c` | compact density |
| `g` | home view |
| `?` | shortcut help |
| `Esc` | close panels / clear search |

## Design

Colors and typography are sampled directly from ftportfolios.com.

| Token | Value | Used for |
|-------|-------|----------|
| Banner navy | `#2F4E75` → `#243B5A` | Masthead, ticker, modal headers |
| Gold rule | `#EDC339` | 4px rule under the masthead |
| Link blue | `#00589F` | Headlines and links |
| Heading navy | `#002F5D` | Section and company titles |
| Orange | `#F0902A` | NEW markers, bullets, focus ring |
| Silver header | `#F8F8F8` → `#CDCDCF` | Section and company header bars |

## Holdings CSV

Editable source of truth: [`data/holdings.csv`](data/holdings.csv)

| Column | Purpose |
|--------|---------|
| `ticker` | Stock symbol |
| `company_name` | Display / search name |
| `cusip` | Optional identifier |
| `classification` | Sector / industry |
| `weighting` | Portfolio weight (%) |
| `active` | `true` / `false` — hide from news |

### Refresh holdings from First Trust

```bash
.venv/bin/python scripts/update_holdings.py
```

## Project layout

```
app/                         # Live FastAPI edition (original)
  payload.py                 # ★ shared dashboard JSON builder
  news.py, sentiment.py, …
  static/                    # ★ shared UI (synced into site/static)
  templates/dashboard.html
site/                        # Static Pages edition (built + committed)
  index.html
  data/dashboard.json
  static/
scripts/
  build_static_data.py       # static snapshot builder
  update_holdings.py
docs/                        # LIVE / STATIC / ARCHITECTURE
.github/workflows/refresh-pages.yml
```

## Documentation

| Doc | Purpose |
|-----|---------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Shared pipeline, data contract, edition differences |
| [docs/LIVE.md](docs/LIVE.md) | FastAPI server ops and APIs |
| [docs/STATIC.md](docs/STATIC.md) | Pages build, cron, local preview |
