"""XPND News Dashboard — live FastAPI application (original / server edition)."""

from __future__ import annotations

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.holdings import load_holdings
from app.payload import alerts_csv_text, build_dashboard_payload, clear_payload_cache
from app.stocks import fetch_stocks

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(
    title="XPND News Dashboard",
    description="Drudge-style news dashboard for First Trust Expanded Technology ETF (XPND)",
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return TEMPLATES.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/dashboard")
async def api_dashboard(
    per_company: int = Query(default=10, ge=1, le=25),
    refresh: bool = Query(default=False),
):
    return JSONResponse(
        build_dashboard_payload(per_company=per_company, refresh=refresh, mode="live")
    )


@app.get("/api/news")
async def api_news(
    per_company: int = Query(default=10, ge=1, le=25),
    refresh: bool = Query(default=False),
):
    return JSONResponse(
        build_dashboard_payload(per_company=per_company, refresh=refresh, mode="live")
    )


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
    return PlainTextResponse(
        alerts_csv_text(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="xpnd-alerts.csv"'},
    )


@app.post("/api/refresh")
async def api_refresh():
    clear_payload_cache()
    return {"ok": True, "message": "Cache cleared"}
