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
DEFAULT_CACHE_SECONDS = 15 * 60
DEFAULT_PER_COMPANY = 10
MAX_WORKERS = 10

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
    """Best-effort unwrap of Google News redirect URLs."""
    try:
        parsed = urlparse(link)
        if "news.google.com" not in parsed.netloc:
            return link
        qs = parse_qs(parsed.query)
        if "url" in qs:
            return unquote(qs["url"][0])
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
    """Collapse the same story from multiple outlets into one row with +N src."""
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
        # Coverage by multiple outlets is itself a signal; keep the harshest read.
        if art.negative_score > primary.negative_score:
            primary.negative_score = art.negative_score
            primary.negative = art.negative_score >= 1
            primary.severity = severity_label(art.negative_score)
    return kept


def fetch_company_articles(
    holding: Holding,
    limit: int = DEFAULT_PER_COMPANY,
    cache_seconds: int = DEFAULT_CACHE_SECONDS,
) -> list[Article]:
    now = time.time()
    cached = _CACHE.get(holding.ticker)
    if cached and cached[0] > now:
        return cached[1][:limit]

    query = quote_plus(holding.search_query)
    url = GOOGLE_NEWS_RSS.format(query=query)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
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
        link = _unwrap_google_link(getattr(entry, "link", "") or "")
        key = hashlib.md5(title.lower().encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)

        published = _parse_date(entry)
        neg_score = score_negative(title)
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
                severity=severity_label(neg_score),
                age_hours=_age_hours(published),
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
    _CACHE[holding.ticker] = (now + cache_seconds, articles)
    return articles


def fetch_all_news(
    holdings: list[Holding],
    per_company: int = DEFAULT_PER_COMPANY,
    cache_seconds: int = DEFAULT_CACHE_SECONDS,
) -> list[CompanyNews]:
    results: dict[str, CompanyNews] = {}

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


def collect_alerts(company_news: list[CompanyNews], limit: int = 20) -> list[dict]:
    """Portfolio-wide negative headlines, newest first."""
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
    alerts.sort(
        key=lambda a: (a["published"] or "", a["negative_score"]),
        reverse=True,
    )
    return alerts[:limit]


def clear_cache() -> None:
    _CACHE.clear()
