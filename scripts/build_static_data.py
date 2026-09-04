#!/usr/bin/env python3
"""Build the static GitHub Pages data snapshot from the shared news pipeline.

Writes:
  site/data/dashboard.json
  site/data/alerts.csv
  site/data/meta.json

Also syncs shared frontend assets into site/static/ so Pages deploys a
self-contained tree without duplicating UI source of truth.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.payload import build_dashboard_payload, alerts_csv_text  # noqa: E402


def sync_assets(site_dir: Path) -> None:
    src = ROOT / "app" / "static"
    dest = site_dir / "static"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def write_index(site_dir: Path, base_path: str) -> None:
    """Render site/index.html from the shared dashboard template markers."""
    template = (ROOT / "app" / "templates" / "dashboard.html").read_text(encoding="utf-8")
    html = template
    html = html.replace('href="/static/style.css"', 'href="static/style.css"')
    html = html.replace('src="/static/app.js"', 'src="static/app.js"')

    live_config = """  <script>
    window.XPND_CONFIG = {
      mode: "live",
      basePath: "/",
      dataUrl: "/api/dashboard",
      csvUrl: "/api/alerts.csv",
      workflowUrl: ""
    };
  </script>"""
    static_config = f"""  <script>
    window.XPND_CONFIG = {{
      mode: "static",
      basePath: {json.dumps(base_path)},
      dataUrl: "data/dashboard.json",
      csvUrl: "data/alerts.csv",
      workflowUrl: "https://github.com/PNelsonFTP/xpnd-drudge/actions/workflows/refresh-pages.yml"
    }};
  </script>"""
    if live_config not in html:
        raise SystemExit("dashboard.html missing expected XPND_CONFIG block for live mode")
    html = html.replace(live_config, static_config)

    html = html.replace(
        '<div class="kbd-row"><kbd>r</kbd><span>refresh headlines</span></div>',
        '<div class="kbd-row"><kbd>r</kbd><span>reload published snapshot</span></div>',
    )
    html = html.replace(
        "XPND DRUDGE — portfolio news for the First Trust Expanded Technology ETF ·",
        "XPND DRUDGE (static) — portfolio news for the First Trust Expanded Technology ETF ·",
    )
    (site_dir / "index.html").write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "site",
        help="Static site root (default: site/)",
    )
    parser.add_argument("--per-company", type=int, default=10)
    parser.add_argument(
        "--base-path",
        default="/xpnd-drudge/",
        help="GitHub Pages base path (informational; assets use relative URLs)",
    )
    args = parser.parse_args()

    site_dir: Path = args.out
    data_dir = site_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    print("Fetching holdings news + quotes…", flush=True)
    payload = build_dashboard_payload(
        per_company=args.per_company, refresh=True, mode="static"
    )

    dashboard_path = data_dir / "dashboard.json"
    dashboard_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    alerts_path = data_dir / "alerts.csv"
    alerts_path.write_text(alerts_csv_text(payload), encoding="utf-8")

    holdings_sync = payload.get("holdingsSync") or {}
    meta = {
        "mode": "static",
        "generatedAt": payload["generatedAt"],
        "company_count": payload["company_count"],
        "headline_count": payload["headline_count"],
        "negative_total": payload["negative_total"],
        "severe_total": payload["severe_total"],
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "basePath": args.base_path,
        "holdingsAsOf": holdings_sync.get("asOf"),
        "holdingsSyncedAt": holdings_sync.get("syncedAt"),
        "rebalanceDetected": bool(holdings_sync.get("rebalanceDetected")),
        "holdingsAdded": holdings_sync.get("added") or [],
        "holdingsRemoved": holdings_sync.get("removed") or [],
    }
    (data_dir / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    sync_assets(site_dir)
    write_index(site_dir, args.base_path)

    # Minimal Pages helpers
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")
    (site_dir / "404.html").write_text(
        '<!DOCTYPE html><meta charset="utf-8">'
        f'<script>location.replace({json.dumps(args.base_path)})</script>'
        f'<p><a href="{args.base_path}">XPND DRUDGE</a></p>\n',
        encoding="utf-8",
    )

    print(
        f"Wrote {dashboard_path.relative_to(ROOT)} "
        f"({payload['headline_count']} headlines, "
        f"{payload['negative_total']} negative, "
        f"{payload['company_count']} companies)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
