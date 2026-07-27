# Static edition (GitHub Pages)

**Status:** maintained · same product features as live, hourly snapshot  
**Tree:** `site/` (generated + committed)  
**Builder:** `scripts/build_static_data.py`  
**Workflow:** `.github/workflows/refresh-pages.yml`  
**Live URL:** https://pnelsonftp.github.io/xpnd-drudge/

## When to use this

- Public URL with **zero server cost**
- Same hosting model as [AI Drudge](https://pnelsonftp.github.io/ai-drudge/) / [Cyber Drudge](https://pnelsonftp.github.io/cyber-drudge/)
- Graceful degradation: last good `site/data/*.json` keeps serving if a fetch fails mid-build (commit only happens when the build succeeds)

## How a refresh works

1. Cron (`10 * * * *` UTC) or **Actions → Refresh static site → Run workflow**
2. `pip install -r requirements.txt`
3. `python scripts/build_static_data.py`
   - Calls `app.payload.build_dashboard_payload(mode="static")`
   - Writes `site/data/dashboard.json`, `alerts.csv`, `meta.json`
   - Syncs `app/static/` → `site/static/`
   - Regenerates `site/index.html` from the live template (relative URLs + static config)
4. Quality gate (companies + headlines present)
5. Commit `site/` if changed
6. Deploy `site/` to GitHub Pages

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
