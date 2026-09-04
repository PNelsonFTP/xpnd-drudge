# Static edition (GitHub Pages)

**Status:** maintained · same product features as live, hourly snapshot  
**Tree:** `site/` (generated + committed)  
**Builder:** `scripts/build_static_data.py`  
**Workflow:** `.github/workflows/refresh-pages.yml`  
**Live URL:** https://pnelsonftp.github.io/xpnd-drudge/

## When to use this

- Public URL with **zero server cost**
- Same hosting model as [AI Drudge](https://pnelsonftp.github.io/ai-drudge/) / [Cyber Drudge](https://pnelsonftp.github.io/cyber-drudge/)
- Graceful degradation: last good `site/data/*.json` keeps serving if a fetch or quality gate fails (commit only happens when the job succeeds)

## How a refresh works

1. Cron (`10 * * * *` UTC) or **Actions → Refresh static site → Run workflow**
2. `pip install -r requirements.txt`
3. Unit tests (`python -m unittest discover -s tests`) — hard-fail, no `continue-on-error`
4. `python scripts/update_holdings.py` (best-effort, `continue-on-error`) — official FT universe → `data/holdings.csv` + reconstitution meta. Dropped names are deactivated. An FT outage must not kill the news build.
5. `python scripts/build_static_data.py`
   - Calls `app.payload.build_dashboard_payload(mode="static")`
   - Writes `site/data/dashboard.json`, `alerts.csv`, `meta.json` (includes `holdingsAsOf` plus coverage summary: `missingNews` count, `quoteCoverage`, `quotesAsOf` when present)
   - Syncs `app/static/` → `site/static/`
   - Regenerates `site/index.html` from the live template (relative URLs + static config)
6. Quality gate (hard fail — last-good `site/` stays live if this step fails before commit):
   - `company_count` 40–60
   - `headline_count` ≥ 100
   - `quoteCoverage` ≥ 0.80 when `coverage` is present
   - fail if `missingNews` > 10 **and** `missingNews / company_count` > 0.20
   - missing `holdingsAsOf` (from `holdingsSync.asOf` or `meta.json`) warns; fails only if `company_count` < 40
7. Commit `site/` **and** holdings files if changed
8. Deploy `site/` to GitHub Pages

Scheduled hourly runs use a separate concurrency group and are **not** cancelled by a later push (`cancel-in-progress` is false for `schedule`). Unit tests also run on PRs via [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) (no scrape, no Pages deploy).

## Local static preview

```bash
source .venv/bin/activate   # or create venv + pip install -r requirements.txt
python scripts/build_static_data.py
cd site && python3 -m http.server 8088
# → http://127.0.0.1:8088/
```

## Client behavior

`window.XPND_CONFIG.mode = "static"`:

| Control | Behavior |
|---------|----------|
| ↻ / `r` | Cache-bust reload of `data/dashboard.json` (does **not** scrape) |
| CSV | Opens `data/alerts.csv` from last build |
| Stale banner (>3h) | Link to run the Actions workflow |
| Auto timer | Re-fetches JSON every 15 minutes (picks up a new hourly deploy) |

## Enabling Pages (first time)

Repo **Settings → Pages → Source → GitHub Actions**.  
The workflow uses `actions/upload-pages-artifact` + `actions/deploy-pages`.

Base path is `/xpnd-drudge/` (repo name). Assets use **relative** URLs, so local `http.server` from `site/` also works.

## Functionality parity

Preserved: company columns, severity, Risk Radar, brief, lead, latest, quotes, portfolio bar, search/sort/filters, bookmarks, read-later, mutes, theme, density, keyboard shortcuts, digest copy, CSV, First Trust theme.

Not available as true live scrape: instant server-side refresh. Use **workflow_dispatch** for an out-of-band rebuild (a few minutes), or run the live edition locally.
