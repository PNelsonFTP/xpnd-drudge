"""XPND News Dashboard — FastAPI application."""

from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.brief import build_brief, build_latest, build_trending, pick_lead
from app.holdings import load_holdings
from app.news import clear_cache, collect_alerts, fetch_all_news
from app.stocks import fetch_stocks, portfolio_stats

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(
    title="XPND News Dashboard",
    description="Drudge-style news dashboard for First Trust Expanded Technology ETF (XPND)",
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Assembled payloads are cheap to reuse; the news layer has its own 15m cache.
_PAYLOAD_CACHE: dict[int, tuple[float, dict]] = {}
PAYLOAD_CACHE_SECONDS = 60


def _dashboard_payload(per_company: int = 10, refresh: bool = False) -> dict:
    now = time.time()
    if refresh:
        clear_cache()
        _PAYLOAD_CACHE.clear()
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
        "companies": [c.to_dict() for c in company_news],
    }
    _PAYLOAD_CACHE[per_company] = (now + PAYLOAD_CACHE_SECONDS, payload)
    return payload


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return TEMPLATES.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/dashboard")
async def api_dashboard(
    per_company: int = Query(default=10, ge=1, le=25),
    refresh: bool = Query(default=False),
):
    return JSONResponse(_dashboard_payload(per_company=per_company, refresh=refresh))


@app.get("/api/news")
async def api_news(
    per_company: int = Query(default=10, ge=1, le=25),
    refresh: bool = Query(default=False),
):
    return JSONResponse(_dashboard_payload(per_company=per_company, refresh=refresh))


@app.get("/api/holdings")
async def api_holdings():
    holdings = load_holdings(active_only=False)
    return [
        {
            "ticker": h.ticker,
            "company_name": h.company_name,
            "cusip": h.cusip,
            "classification": h.classification,
            "weighting": h.weighting,
            "active": h.active,
        }
        for h in holdings
    ]


@app.get("/api/stocks")
async def api_stocks():
    return JSONResponse(fetch_stocks())


@app.get("/api/alerts.csv", response_class=PlainTextResponse)
async def api_alerts_csv():
    """Negative headlines as CSV for compliance logs / morning meetings."""
    payload = _dashboard_payload()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["ticker", "company", "severity", "score", "published", "source", "headline", "link"]
    )
    for a in payload["alerts"]:
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
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="xpnd-alerts.csv"'},
    )


@app.post("/api/refresh")
async def api_refresh():
    clear_cache()
    _PAYLOAD_CACHE.clear()
    return {"ok": True, "message": "Cache cleared"}
