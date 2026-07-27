"""Fetch quotes for XPND holdings (Yahoo Finance, fail-soft)."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

from app.holdings import Holding, load_holdings

HEADERS = {
    "User-Agent": "Mozilla/5.0 XPNDDrudgeBot/1.0",
}

_CACHE: tuple[float, dict] | None = None
CACHE_SECONDS = 10 * 60
TIMEOUT = 5
MAX_WORKERS = 8


def _yahoo_quote(symbol: str) -> Optional[dict]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{symbol}?interval=1d&range=5d"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = (data.get("chart") or {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        price = meta.get("regularMarketPrice")
        if not isinstance(price, (int, float)):
            return None

        closes = (
            ((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close")
            or []
        )
        prior = None
        for i in range(len(closes) - 2, -1, -1):
            c = closes[i]
            if isinstance(c, (int, float)):
                prior = c
                break
        ref = prior or meta.get("previousClose") or meta.get("chartPreviousClose") or price
        change = float(price) - float(ref)
        pct = (change / float(ref) * 100.0) if ref else 0.0
        return {
            "symbol": symbol,
            "price": round(float(price), 2),
            "change": round(change, 2),
            "changePct": round(pct, 2),
        }
    except Exception:  # noqa: BLE001
        return None


def fetch_stocks(
    holdings: list[Holding] | None = None,
    limit: Optional[int] = None,
) -> dict[str, dict]:
    """Return quotes for holdings (all by default). Cached ~10 minutes."""
    global _CACHE
    now = time.time()
    if _CACHE and _CACHE[0] > now:
        return _CACHE[1]

    hs = holdings or load_holdings()
    tickers = [h.ticker for h in (hs[:limit] if limit else hs)]
    out: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_yahoo_quote, t): t for t in tickers}
        for fut in as_completed(futures):
            q = fut.result()
            if q:
                out[q["symbol"]] = q

    # Preserve weight order
    ordered = {t: out[t] for t in tickers if t in out}
    _CACHE = (now + CACHE_SECONDS, ordered)
    return ordered


def portfolio_stats(
    holdings: list[Holding], quotes: dict[str, dict]
) -> dict[str, float | int]:
    """Weight-adjusted day move plus a gainer/loser split for the summary bar."""
    total_weight = 0.0
    weighted = 0.0
    gainers = 0
    losers = 0
    for h in holdings:
        q = quotes.get(h.ticker)
        if not q:
            continue
        total_weight += h.weighting
        weighted += h.weighting * float(q["changePct"])
        if q["changePct"] >= 0:
            gainers += 1
        else:
            losers += 1
    return {
        "weightedChangePct": round(weighted / total_weight, 2) if total_weight else 0.0,
        "gainers": gainers,
        "losers": losers,
        "covered": gainers + losers,
    }
