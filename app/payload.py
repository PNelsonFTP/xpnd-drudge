"""Shared dashboard payload builder used by the live FastAPI app and the static site build."""

from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timezone

from app.brief import build_brief, build_latest, build_trending, pick_lead
from app.holdings import load_holdings, load_holdings_meta
from app.news import clear_cache, collect_alerts, fetch_all_news
from app.stocks import clear_cache as clear_stocks_cache
from app.stocks import fetch_stocks, portfolio_stats

# Assembled payloads are cheap to reuse; the news layer has its own 15m cache.
_PAYLOAD_CACHE: dict[int, tuple[float, dict]] = {}
PAYLOAD_CACHE_SECONDS = 60


def clear_payload_cache() -> None:
    clear_cache()
    clear_stocks_cache()
    _PAYLOAD_CACHE.clear()


def build_dashboard_payload(
    per_company: int = 10,
    *,
    refresh: bool = False,
    mode: str = "live",
) -> dict:
    """Assemble the full dashboard JSON contract.

    ``mode`` is recorded on the payload so the client can adapt UX
    (``live`` = FastAPI; ``static`` = GitHub Pages snapshot).
    """
    now = time.time()
    if refresh:
        clear_payload_cache()
    else:
        cached = _PAYLOAD_CACHE.get(per_company)
        if cached and cached[0] > now:
            return cached[1]

    holdings = load_holdings()
    company_news = fetch_all_news(holdings, per_company=per_company)
    alerts = collect_alerts(company_news, limit=20)
    lead = pick_lead(company_news)
    trending = build_trending(alerts)
    latest = build_latest(company_news, limit=15)
    brief = build_brief(company_news, lead=lead, alerts=alerts)
    quotes = fetch_stocks(holdings)

    sectors = sorted({c.classification for c in company_news if c.classification})
    severe = sum(
        1 for c in company_news for a in c.articles if a.severity == "severe"
    )

    payload = {
        "mode": mode,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "company_count": len(holdings),
        "negative_total": sum(c.negative_count for c in company_news),
        "severe_total": severe,
        "headline_count": sum(len(c.articles) for c in company_news),
        "per_company": per_company,
        "sectors": sectors,
        "brief": brief,
        "lead": lead,
        "trending": trending,
        "latest": latest,
        "alerts": alerts,
        "stocks": quotes,
        "portfolio": portfolio_stats(holdings, quotes),
        "holdingsSync": load_holdings_meta(),
        "companies": [c.to_dict() for c in company_news],
    }
    _PAYLOAD_CACHE[per_company] = (now + PAYLOAD_CACHE_SECONDS, payload)
    return payload


def alerts_csv_text(payload: dict | None = None) -> str:
    """Negative headlines as CSV for compliance logs / morning meetings."""
    data = payload or build_dashboard_payload()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["ticker", "company", "severity", "score", "published", "source", "headline", "link"]
    )
    for a in data.get("alerts") or []:
        writer.writerow(
            [
                a["ticker"],
                a["company_name"],
                a.get("severity", ""),
                a.get("negative_score", 0),
                a.get("published") or "",
                a.get("source") or "",
                a["title"],
                a["link"],
            ]
        )
    return buf.getvalue()
