"""Fetch company news via Google News RSS, cache, and sort by recency."""

from __future__ import annotations

import hashlib
import html
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

import feedparser
import requests

from app.holdings import Holding
from app.sentiment import score_negative

GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# In-memory cache: ticker -> (expires_epoch, articles)
_CACHE: dict[str, tuple[float, list["Article"]]] = {}
# ticker -> "ok" | "empty" | "error" from the last live fetch
_FEED_STATS: dict[str, str] = {}
DEFAULT_CACHE_SECONDS = 15 * 60
ERROR_CACHE_SECONDS = 90
DEFAULT_PER_COMPANY = 10
MAX_WORKERS = 10
# Drop week-old filler after scoring; elevated/severe may stay within the window.
MAX_PANEL_AGE_HOURS = 7 * 24

# Titles this similar are treated as the same story from different outlets.
GROUPING_THRESHOLD = 0.55

# Quote pages, option chains and message boards are never portfolio news.
JUNK_TITLE_PATTERNS = [
    r"\(\w{1,6}\d{6}[CP]\d{4,}\)",
    r"\b\d+\.\d{2,3}\s+(?:call|put)s?\b",
    r"\bstock forum\b",
    r"historical prices and data",
    r"interactive stock chart",
    r"stock price,?\s*news,?\s*quote (?:and|&) history",
    r"\bstock price quote\b",
    r"\boption(?:s)? chain\b",
    r"\bmessage board\b",
    # Tokenized-stock converters / FX quote terminals
    r"\btokenized\s+stocks?\b",
    r"\bxstock\b",
    r"price today\s*\|",
    r"live .{0,40} to (?:gbp|usd|eur)\b",
    r"\|Price:\s*[\d.]+",
    r"\|Chg%:",
    r"\bPrice:\s*[\d.]+\s*\|",
    r"\b[A-Z]{1,6}\|[A-Za-z][^|]{0,40}\|Price:",
]

# Real filings, but 13F/ownership chatter buries actual company news.
LOW_VALUE_PATTERNS = [
    r"\b(?:acquires|buys|sells|has|takes|lowers|raises|boosts|trims|cuts|reduces|increases|grows|lifts)\b.{0,50}\b(?:stake|position|holdings?|shares of|new position)\b",
    r"\bshares (?:sold|bought|acquired|purchased) by\b",
    r"\b(?:purchases|acquires|buys|sells|sold|bought)\s+[\d,]+\s+shares\b",
    r"\b[\d,]+\s+shares\b.{0,70}\b(?:acquired|purchased|bought|sold)\s+by\b",
    r"\bshares?\s+(?:of|in)\b.{0,70}\b(?:acquired|purchased|sold|bought)\s+by\b",
    r"\b(?:invests|invested)\s+\$[\d.]+\s+(?:million|billion)\b",
    r"\b\$[\d.]+ (?:million|billion) (?:stake|position|holdings?)\b",
    r"\bshort interest\b",
    r"\binsider (?:selling|buying|transaction)\b",
    r"\b13[fF]\b",
    # MarketBeat / Stock Titan 13F wallpaper
    r"\bpurchases? new (?:position|holdings?)\b",
    r"\bmakes? new \$[\d.,]+\s*(?:million|billion)?\s+investment\b",
    r"\b(?:decreases?|increases?)\s+(?:its\s+)?(?:position|holdings?|stake)\b",
    r"\b(?:stock )?position\s+(?:increased|reduced|boosted|lowered|lifted|decreased)\b",
    r"\b(?:officer|director|ceo|cfo|coo|insider)s?\s+sells?\s+\$",
    r"\b(?:officer|director|ceo|cfo|coo|insider)s?\s+sells?\s+[\d,]+\s+shares\b",
    r"\b(?:officer|director|ceo|cfo|coo)\b.{0,40}\bsells?\b.{0,25}(?:\$|shares)",
    r"\binsider sold shares worth\b",
    r"\bform\s*-?\s*4\b",
]

_JUNK = [re.compile(p, re.I) for p in JUNK_TITLE_PATTERNS]
_LOW_VALUE = [re.compile(p, re.I) for p in LOW_VALUE_PATTERNS]


def is_junk(title: str) -> bool:
    return any(rx.search(title) for rx in _JUNK)


def is_low_value(title: str) -> bool:
    return any(rx.search(title) for rx in _LOW_VALUE)


_STOPWORDS = {
    "a", "an", "and", "the", "for", "of", "to", "in", "on", "at", "by", "is",
    "are", "was", "were", "as", "with", "from", "after", "amid", "its", "it",
    "this", "that", "will", "has", "have", "be", "but", "or", "not", "into",
    "over", "up", "down", "new", "says", "said", "why", "how", "what",
}


def severity_label(score: int) -> str:
    """Negative severity tier used for badge styling."""
    if score >= 4:
        return "severe"
    if score >= 2:
        return "elevated"
    if score >= 1:
        return "watch"
    return "none"


def title_relevant(title: str, holding: Holding) -> bool:
    """Drop cross-ticker / macro bleed that Google attached to this query."""
    if not title:
        return False
    t = title.lower()
    ticker = holding.ticker
    # Cashtag always counts ($ON, $APP) even for ambiguous English-word tickers.
    if f"${ticker.lower()}" in t:
        return True
    # Ticker as a symbol — keep case so "on" / "App" are not treated as ON / APP.
    if re.search(rf"(?<![A-Za-z]){re.escape(ticker)}(?![A-Za-z])", title):
        return True
    tokens = holding.name_tokens
    hits = [tok for tok in tokens if tok in t]
    if any(len(h) >= 5 for h in hits):
        return True
    if len(hits) >= 2:
        return True
    parts = holding.clean_name.lower().split()
    if len(parts) >= 2 and " ".join(parts[:2]) in t:
        return True
    return False


@dataclass
class RelatedSource:
    source: str
    link: str
    published: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "link": self.link,
            "published": self.published.isoformat() if self.published else None,
        }


@dataclass
class Article:
    id: str
    title: str
    link: str
    source: str
    published: Optional[datetime]
    published_display: str
    negative: bool
    negative_score: int
    severity: str = "none"
    age_hours: Optional[float] = None
    ticker: str = ""
    low_value: bool = False
    related: list[RelatedSource] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.published:
            d["published"] = self.published.isoformat()
        d["related"] = [r.to_dict() for r in self.related]
        d["related_count"] = len(self.related)
        return d


def _article_id(ticker: str, title: str, link: str) -> str:
    raw = f"{ticker}|{title.lower().strip()}|{link}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


@dataclass
class CompanyNews:
    ticker: str
    company_name: str
    classification: str
    weighting: float
    articles: list[Article] = field(default_factory=list)
    negative_count: int = 0
    newest: Optional[datetime] = None

    @property
    def max_severity(self) -> str:
        best = 0
        for a in self.articles:
            if a.low_value:
                continue
            best = max(best, a.negative_score)
        return severity_label(best)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "classification": self.classification,
            "weighting": self.weighting,
            "negative_count": self.negative_count,
            "max_severity": self.max_severity,
            "newest": self.newest.isoformat() if self.newest else None,
            "articles": [a.to_dict() for a in self.articles],
        }


def _unwrap_google_link(link: str) -> str:
    """Best-effort unwrap of Google News / google.com/url redirect URLs."""
    try:
        parsed = urlparse(link)
        host = (parsed.netloc or "").lower()
        if "google." not in host:
            return link
        qs = parse_qs(parsed.query)
        for key in ("url", "q", "u"):
            vals = qs.get(key) or []
            if not vals:
                continue
            candidate = unquote(vals[0])
            if candidate.startswith("http"):
                return candidate
        if parsed.fragment:
            fqs = parse_qs(parsed.fragment)
            for key in ("url", "q"):
                vals = fqs.get(key) or []
                if vals:
                    candidate = unquote(vals[0])
                    if candidate.startswith("http"):
                        return candidate
    except Exception:  # noqa: BLE001
        pass
    return link


def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            continue
    for attr in ("published_parsed", "updated_parsed"):
        struct = getattr(entry, attr, None)
        if struct:
            try:
                return datetime(*struct[:6], tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001
                continue
    return None


def _format_date(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    local = dt.astimezone()
    return local.strftime("%b %d %I:%M %p")


def _age_hours(dt: Optional[datetime]) -> Optional[float]:
    if not dt:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)


def _clean_title(title: str, source: str = "") -> str:
    """Normalize whitespace and drop the trailing ' - Outlet' Google appends."""
    title = html.unescape(title or "")
    title = re.sub(r"\s+", " ", title).strip()
    if source:
        suffix = f" - {source}"
        if title.lower().endswith(suffix.lower()):
            title = title[: -len(suffix)].strip()
    else:
        # No source metadata: still strip a short trailing "- Outlet Name".
        title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title).strip()
    return title


def _tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def group_articles(articles: list[Article]) -> list[Article]:
    """Collapse the same story from multiple outlets into one row with +N src.

    Related outlets attach as sources. The primary title keeps its own score —
    a harsher rewrite from another site must not inflate a milder headline.
    """
    kept: list[Article] = []
    token_cache: list[set[str]] = []

    for art in articles:
        toks = _tokens(art.title)
        match_idx = None
        for i, existing_toks in enumerate(token_cache):
            if _jaccard(toks, existing_toks) >= GROUPING_THRESHOLD:
                match_idx = i
                break
        if match_idx is None:
            kept.append(art)
            token_cache.append(toks)
            continue

        primary = kept[match_idx]
        if art.source and art.source != primary.source:
            if not any(r.source == art.source for r in primary.related):
                primary.related.append(
                    RelatedSource(
                        source=art.source, link=art.link, published=art.published
                    )
                )
    return kept


def last_feed_stats() -> dict[str, str]:
    """Per-ticker fetch outcome from the most recent live pull."""
    return dict(_FEED_STATS)


def news_coverage(company_news: list[CompanyNews]) -> dict:
    """Summarize missing / failed / empty feeds for the last news pull."""
    missing = [c.ticker for c in company_news if not c.articles]
    failures = [t for t, status in _FEED_STATS.items() if status == "error"]
    empty = [t for t, status in _FEED_STATS.items() if status == "empty"]
    return {
        "missingNews": missing,
        "feedFailures": failures,
        "emptyFeeds": empty,
        "articleCount": sum(len(c.articles) for c in company_news),
    }


def fetch_company_articles(
    holding: Holding,
    limit: int = DEFAULT_PER_COMPANY,
    cache_seconds: int = DEFAULT_CACHE_SECONDS,
) -> list[Article]:
    now = time.time()
    cached = _CACHE.get(holding.ticker)
    if cached and cached[0] > now:
        arts = cached[1][:limit]
        _FEED_STATS.setdefault(
            holding.ticker, "ok" if arts else "empty"
        )
        return arts

    query = quote_plus(f"{holding.search_query} when:7d")
    url = GOOGLE_NEWS_RSS.format(query=query)
    ok = False
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        ok = True
    except Exception:  # noqa: BLE001
        feed = feedparser.parse("")

    articles: list[Article] = []
    seen: set[str] = set()
    for entry in feed.entries:
        source = ""
        if hasattr(entry, "source") and getattr(entry.source, "title", None):
            source = entry.source.title
        title = _clean_title(getattr(entry, "title", ""), source)
        if not title or is_junk(title):
            continue
        if not title_relevant(title, holding):
            continue
        link = _unwrap_google_link(getattr(entry, "link", "") or "")
        key = hashlib.md5(title.lower().encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)

        published = _parse_date(entry)
        age = _age_hours(published)
        neg_score = score_negative(title)
        sev = severity_label(neg_score)
        # Age-out stale filler; keep elevated/severe through the 7d window.
        if age is not None and age > MAX_PANEL_AGE_HOURS and sev in ("none", "watch"):
            continue
        articles.append(
            Article(
                id=_article_id(holding.ticker, title, link),
                title=title,
                link=link,
                source=source,
                published=published,
                published_display=_format_date(published),
                negative=neg_score >= 1,
                negative_score=neg_score,
                severity=sev,
                age_hours=age,
                ticker=holding.ticker,
                low_value=is_low_value(title),
            )
        )

    # Recency leads, but ownership/filing chatter sinks below real coverage.
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    articles.sort(
        key=lambda a: (
            not a.low_value,
            a.published or epoch,
            a.negative_score,
        ),
        reverse=True,
    )
    articles = group_articles(articles)[:limit]
    if not ok:
        ttl = min(ERROR_CACHE_SECONDS, cache_seconds)
        _FEED_STATS[holding.ticker] = "error"
    elif not articles:
        ttl = min(ERROR_CACHE_SECONDS, cache_seconds)
        _FEED_STATS[holding.ticker] = "empty"
    else:
        ttl = cache_seconds
        _FEED_STATS[holding.ticker] = "ok"
    _CACHE[holding.ticker] = (now + ttl, articles)
    return articles


def fetch_all_news(
    holdings: list[Holding],
    per_company: int = DEFAULT_PER_COMPANY,
    cache_seconds: int = DEFAULT_CACHE_SECONDS,
) -> list[CompanyNews]:
    results: dict[str, CompanyNews] = {}
    _FEED_STATS.clear()

    def work(h: Holding) -> CompanyNews:
        arts = fetch_company_articles(h, limit=per_company, cache_seconds=cache_seconds)
        newest = next((a.published for a in arts if a.published), None)
        return CompanyNews(
            ticker=h.ticker,
            company_name=h.company_name,
            classification=h.classification,
            weighting=h.weighting,
            articles=arts,
            negative_count=sum(1 for a in arts if a.negative and not a.low_value),
            newest=newest,
        )

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(work, h): h.ticker for h in holdings}
        for fut in as_completed(futures):
            item = fut.result()
            results[item.ticker] = item

    # Portfolio weight order keeps the layout familiar; the client re-sorts on
    # demand and severity badges surface what needs attention.
    return [results[h.ticker] for h in holdings if h.ticker in results]


def collect_alerts(
    company_news: list[CompanyNews],
    limit: int = 30,
    lead: Optional[dict] = None,
) -> list[dict]:
    """Portfolio-wide negative headlines.

    Prefer elevated/severe (and the lead if it is negative), then watch.
    """
    alerts: list[dict] = []
    for cn in company_news:
        for art in cn.articles:
            if not art.negative or art.low_value:
                continue
            alerts.append(
                {
                    "id": art.id,
                    "ticker": cn.ticker,
                    "company_name": cn.company_name,
                    "title": art.title,
                    "link": art.link,
                    "source": art.source,
                    "published": art.published.isoformat() if art.published else None,
                    "published_display": art.published_display,
                    "negative_score": art.negative_score,
                    "severity": art.severity,
                    "related_count": len(art.related),
                    "negative": True,
                }
            )

    if lead and lead.get("negative") and lead.get("id"):
        if not any(a["id"] == lead["id"] for a in alerts):
            alerts.append(
                {
                    "id": lead["id"],
                    "ticker": lead.get("ticker", ""),
                    "company_name": lead.get("company_name", ""),
                    "title": lead.get("title", ""),
                    "link": lead.get("link", ""),
                    "source": lead.get("source", ""),
                    "published": lead.get("published"),
                    "published_display": lead.get("published_display", ""),
                    "negative_score": lead.get("negative_score", 1),
                    "severity": lead.get("severity", "watch"),
                    "related_count": len(lead.get("related") or []),
                    "negative": True,
                }
            )

    sev_rank = {"severe": 3, "elevated": 2, "watch": 1, "none": 0}

    def sort_key(a: dict) -> tuple:
        return (
            sev_rank.get(a.get("severity", "watch"), 0),
            a.get("negative_score", 0),
            a.get("published") or "",
        )

    must = [a for a in alerts if a.get("severity") in ("severe", "elevated")]
    if lead and lead.get("negative") and lead.get("id"):
        must_ids = {a["id"] for a in must}
        for a in alerts:
            if a["id"] == lead["id"] and a["id"] not in must_ids:
                must.append(a)
                break
    rest = [a for a in alerts if a["id"] not in {m["id"] for m in must}]
    must.sort(key=sort_key, reverse=True)
    rest.sort(key=sort_key, reverse=True)
    merged = must + rest
    out: list[dict] = []
    seen: set[str] = set()
    for a in merged:
        if a["id"] in seen:
            continue
        seen.add(a["id"])
        out.append(a)
        if len(out) >= limit:
            break
    return out


def clear_cache() -> None:
    _CACHE.clear()
    _FEED_STATS.clear()
