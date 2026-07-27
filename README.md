# XPND DRUDGE

Drudge-style portfolio news dashboard for the **First Trust Expanded Technology ETF (XPND)**.

Built for portfolio managers: recent headlines first, negative/risk news highlighted, one section per holding. UI patterns borrowed from [AI Drudge](https://pnelsonftp.github.io/ai-drudge/) and [Cyber Drudge](https://pnelsonftp.github.io/cyber-drudge/).

## Quick start

```bash
./run.sh
# or
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Deploy

This is a live FastAPI app (not a static GitHub Pages site like AI/Cyber Drudge). The easiest free host is [Render](https://render.com):

1. New → Web Service → connect this GitHub repo
2. Runtime: Python · Build: `pip install -r requirements.txt` · Start: leave the `Procfile` as-is
3. Deploy — public URL will look like `https://xpnd-drudge.onrender.com`

Or any PaaS that reads a `Procfile` (Railway, Heroku-compatible).

## Features

| Feature | Notes |
|---------|--------|
| Company sections | One block per holding with live price chip and weight |
| Severity tiers | `NEG` (elevated) and `SEVERE` badges, red/orange treatment |
| Risk Radar | Portfolio-wide negative headlines, newest first |
| Daily Brief | Curated summary of risk + freshest items |
| Lead Story | Highest-impact recent headline with "also covered by" |
| Latest | Reverse-chronological across the book, grouped by day |
| Portfolio summary bar | Weight-adjusted day move, gainers/losers, headline counts |
| Jump index | Ticker chips with negative counts; click to scroll |
| Stock ticker | All holdings via Yahoo Finance, red dot marks bad news |
| Story grouping | Duplicate coverage collapses into `+N src` |
| Noise filtering | Option chains/quote pages dropped, 13F chatter demoted |
| Sort | Weight, newest news, most negative, biggest mover, A–Z |
| Filters | Negative only, last 24h, unread only, by sector |
| Search | Headline, source, ticker, company, sector |
| Read state | Visited headlines dim; "unread only" filter |
| ★ Bookmarks / ⏷ Read later | Persisted in `localStorage` with snapshots |
| Mute company or source | Manage via ✕ panel |
| Copy digest / CSV | Clipboard risk digest and `alerts.csv` download |
| First Trust theme | Brand palette by default, navy night mode via `t` |
| Density toggle | Comfortable or compact rows |
| Auto-refresh | Every 10 minutes with countdown, pauses when hidden |
| Shareable URLs | Search, sort, sector and filters sync to the hash |
| Keyboard shortcuts | `/ r t n h u b l d c g ?` — press `?` for the list |
| Print layout | Two-column black-on-white morning-meeting handout |

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `/` | focus search |
| `r` | refresh headlines |
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

Colors and typography are sampled directly from ftportfolios.com so the dashboard reads as a
First Trust property. Red is reserved for risk; orange marks fresh items.

| Token | Value | Used for |
|-------|-------|----------|
| Banner navy | `#2F4E75` → `#243B5A` | Masthead, ticker, modal headers |
| Gold rule | `#EDC339` | 4px rule under the masthead |
| Link blue | `#00589F` | Headlines and links |
| Heading navy | `#002F5D` | Section and company titles |
| Orange | `#F0902A` | NEW markers, bullets, focus ring |
| Silver header | `#F8F8F8` → `#CDCDCF` | Section and company header bars |
| Page stripe | `#EEEEEE` with 1px `#DDDDDD` rules | Page background outside the content shell |
| Rules | `#BFBFBF` / `#C0C0C0` | Borders |

Type is Arial / Helvetica throughout, matching First Trust's stack.

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
python scripts/update_holdings.py
```

Scrapes [XPND holdings](https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Ticker=XPND) and merges into the CSV (keeps manual adds + inactive flags).

## API

- `GET /api/dashboard` — full payload (news, brief, lead, risk radar, quotes, portfolio stats)
- `GET /api/news` — same as dashboard
- `GET /api/holdings` — holdings JSON
- `GET /api/stocks` — quote bar JSON
- `GET /api/alerts.csv` — negative headlines as CSV
- `POST /api/refresh` — clear news + payload caches

Caching: news 15 minutes, quotes 10 minutes, assembled payload 60 seconds. Add `?refresh=true` to bypass.

## Project layout

```
data/holdings.csv
scripts/update_holdings.py
app/main.py
app/news.py          # Google News RSS + cache
app/sentiment.py     # negative headline scoring
app/stocks.py        # Yahoo quotes
app/brief.py         # curated brief / lead / latest
app/templates/dashboard.html
app/static/style.css
app/static/app.js
```
