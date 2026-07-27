"""Curated daily brief from portfolio news (no LLM required)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.news import Article, CompanyNews


def build_brief(
    companies: list[CompanyNews],
    lead: Optional[dict] = None,
    alerts: Optional[list[dict]] = None,
) -> dict:
    """Assemble a short curated brief for the dashboard header."""
    alerts = alerts or []
    neg_companies = [c for c in companies if c.negative_count > 0]
    total_arts = sum(len(c.articles) for c in companies)
    freshest: list[tuple[CompanyNews, Article]] = []
    for c in companies:
        for a in c.articles:
            if a.published and not a.low_value:
                freshest.append((c, a))
    freshest.sort(
        key=lambda pair: pair[1].published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    if lead:
        headline = lead["title"]
    elif alerts:
        headline = alerts[0]["title"]
    elif freshest:
        c, a = freshest[0]
        headline = f"{c.ticker}: {a.title}"
    else:
        headline = "No material portfolio headlines in the latest pull."

    bullets: list[str] = []
    if alerts:
        tickers = sorted({a["ticker"] for a in alerts[:8]})
        bullets.append(
            f"{len(alerts)} negative/risk headline{'s' if len(alerts) != 1 else ''} "
            f"across {', '.join(tickers[:8])}{'…' if len(tickers) > 8 else ''}."
        )
    if neg_companies:
        top = sorted(neg_companies, key=lambda c: (-c.negative_count, -c.weighting))[:5]
        bullets.append(
            "Watch list: "
            + ", ".join(f"{c.ticker} ({c.negative_count})" for c in top)
            + "."
        )
    if freshest:
        recent = freshest[:3]
        for c, a in recent:
            age = ""
            if a.age_hours is not None:
                if a.age_hours < 1:
                    age = " <1h"
                elif a.age_hours < 24:
                    age = f" {int(a.age_hours)}h"
                else:
                    age = f" {int(a.age_hours / 24)}d"
            flag = " [NEG]" if a.negative else ""
            bullets.append(f"{c.ticker}{age}{flag}: {a.title[:110]}")
            if len(bullets) >= 6:
                break

    if not bullets:
        bullets.append(f"Tracking {len(companies)} holdings · {total_arts} headlines.")

    return {
        "headline": headline[:220],
        "bullets": bullets[:6],
        "source": "curated",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


def pick_lead(companies: list[CompanyNews]) -> Optional[dict]:
    """Highest-impact recent story: prefer negative, then freshest."""
    candidates: list[tuple[float, CompanyNews, Article]] = []
    for c in companies:
        for a in c.articles:
            if not a.published or a.low_value:
                continue
            age_h = a.age_hours if a.age_hours is not None else 999
            if age_h > 96:
                continue
            # Score: negative weight + recency + portfolio weight
            recency = max(0.0, 48.0 - age_h) / 48.0
            score = (
                a.negative_score * 3.0
                + (2.0 if a.negative else 0.0)
                + recency * 2.0
                + min(c.weighting, 6.0) / 6.0
            )
            candidates.append((score, c, a))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    _score, c, a = candidates[0]
    return {
        "id": a.id,
        "ticker": c.ticker,
        "company_name": c.company_name,
        "title": a.title,
        "link": a.link,
        "source": a.source,
        "published": a.published.isoformat() if a.published else None,
        "published_display": a.published_display,
        "negative": a.negative,
        "negative_score": a.negative_score,
        "severity": a.severity,
        "related": [r.to_dict() for r in a.related],
        "snippet": f"{c.company_name} ({c.ticker}) · {c.weighting:.2f}% of XPND",
    }


def _norm_title(title: str) -> str:
    return " ".join(sorted(title.lower().split()))[:160]


def build_trending(alerts: list[dict], limit: int = 8) -> list[dict]:
    """Surface portfolio risk headlines as the trending rail."""
    out: list[dict] = []
    seen: set[str] = set()
    for a in alerts:
        key = _norm_title(a["title"])
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "id": a.get("id") or f"{a['ticker']}:{a['title'][:40]}",
                "title": a["title"],
                "primaryUrl": a["link"],
                "ticker": a["ticker"],
                "source": a.get("source", ""),
                "published": a.get("published"),
                "severity": a.get("severity", "watch"),
                "sources": [a["source"]] if a.get("source") else [a["ticker"]],
                "priority": "critical" if a.get("negative_score", 0) >= 2 else "high",
                "negative": True,
            }
        )
        if len(out) >= limit:
            break
    return out


def build_latest(companies: list[CompanyNews], limit: int = 15) -> list[dict]:
    items: list[dict] = []
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    for c in companies:
        for a in c.articles:
            if a.low_value:
                continue
            key = _norm_title(a.title)
            if a.id in seen_ids or key in seen_titles:
                continue
            seen_ids.add(a.id)
            seen_titles.add(key)
            items.append(
                {
                    "id": a.id,
                    "ticker": c.ticker,
                    "company_name": c.company_name,
                    "title": a.title,
                    "link": a.link,
                    "source": a.source,
                    "published": a.published.isoformat() if a.published else None,
                    "negative": a.negative,
                    "negative_score": a.negative_score,
                    "severity": a.severity,
                }
            )
    items.sort(key=lambda x: x["published"] or "", reverse=True)
    return items[:limit]
