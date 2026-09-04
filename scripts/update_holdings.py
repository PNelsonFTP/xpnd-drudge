#!/usr/bin/env python3
"""Scrape XPND ETF holdings from First Trust and update data/holdings.csv.

The official holdings page is the source of truth for the *active* universe.
Names that leave the fund are deactivated (kept for history) instead of
remaining live news sections. Composition adds/removes are recorded in
data/holdings_meta.json so the dashboard can flag a reconstitution.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.holdings import (  # noqa: E402
    DEFAULT_CSV,
    DEFAULT_META,
    assert_scrape_plausible,
    build_holdings_meta,
    diff_holdings,
    load_existing_rows,
    merge_official_holdings,
    write_holdings_csv,
    write_holdings_meta,
)

HOLDINGS_URL = (
    "https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Ticker=XPND"
)
SKIP_TICKERS = {"$USD", "USD", "CASH"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

ASOF_PATTERNS = [
    re.compile(
        r"as of(?:\s+the\s+close\s+of\s+business)?(?:\s+on)?\s+"
        r"([A-Za-z]{3,9}\.?\s+\d{1,2},\s+\d{4})",
        re.I,
    ),
    re.compile(
        r"as of(?:\s+the\s+close\s+of\s+business)?(?:\s+on)?\s+"
        r"(\d{1,2}/\d{1,2}/\d{2,4})",
        re.I,
    ),
    re.compile(
        r"holdings(?:\s+are)?\s+as of[:\s]+"
        r"([A-Za-z]{3,9}\.?\s+\d{1,2},\s+\d{4})",
        re.I,
    ),
]


def clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"\s*\(Class [A-Z]\)\s*$", "", name, flags=re.I)
    name = name.replace(", Inc.", " Inc.").replace(", Inc", " Inc.")
    return name


def parse_weight(raw: str) -> str:
    return raw.replace("%", "").strip()


def parse_as_of(html: str) -> str | None:
    text = re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" "))
    for rx in ASOF_PATTERNS:
        match = rx.search(text)
        if not match:
            continue
        raw = match.group(1).strip()
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%b. %d, %Y", "%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
        return raw
    return None


def scrape_holdings(url: str = HOLDINGS_URL) -> tuple[list[dict], str | None]:
    resp = requests.get(url, headers=HEADERS, timeout=45)
    resp.raise_for_status()
    as_of = parse_as_of(resp.text)
    soup = BeautifulSoup(resp.text, "html.parser")

    rows: list[dict] = []
    for table in soup.find_all("table"):
        # FT holdings tables often use <td> header cells, not <th>.
        header_texts = [
            c.get_text(strip=True).lower()
            for c in table.find_all(["th", "td"])[:12]
        ]
        if "security name" not in header_texts or "identifier" not in header_texts:
            continue

        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 7:
                continue
            name, ticker, cusip, classification, _shares, _mv, weight = cells[:7]
            if name.lower() == "security name":
                continue
            ticker = ticker.strip().upper()
            if not ticker or ticker in SKIP_TICKERS:
                continue
            if ticker.startswith("$"):
                continue
            if not re.fullmatch(r"[A-Z]{1,5}", ticker):
                continue
            rows.append(
                {
                    "ticker": ticker,
                    "company_name": clean_name(name),
                    "cusip": cusip.strip(),
                    "classification": classification.strip(),
                    "weighting": parse_weight(weight),
                    "active": "true",
                }
            )
        if rows:
            break

    if not rows:
        raise RuntimeError("No holdings rows found on holdings page.")
    return rows, as_of


def format_report(diff: dict, as_of: str | None) -> str:
    lines = [
        f"Official equity names: {diff['currentCount']}"
        + (f" (as of {as_of})" if as_of else ""),
        f"Previous active names: {diff['previousCount']}",
    ]
    if diff["added"]:
        lines.append("ADDED:   " + ", ".join(diff["added"]))
    if diff["removed"]:
        lines.append("REMOVED: " + ", ".join(diff["removed"]))
    if diff["weightChanges"]:
        notable = ", ".join(
            f"{c['ticker']} {c['from']:.2f}->{c['to']:.2f}"
            for c in diff["weightChanges"][:12]
        )
        lines.append(f"WEIGHT (≥0.5pp): {notable}")
    if diff["rebalanceDetected"]:
        lines.append("REBALANCE: composition changed (adds and/or drops).")
    else:
        lines.append("REBALANCE: no composition change.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Update XPND holdings CSV")
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help=f"Path to holdings CSV (default: {DEFAULT_CSV})",
    )
    parser.add_argument(
        "--meta",
        type=Path,
        default=DEFAULT_META,
        help=f"Path to holdings meta JSON (default: {DEFAULT_META})",
    )
    parser.add_argument(
        "--url",
        default=HOLDINGS_URL,
        help="Holdings page URL",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Scrape and report drift without writing files (exit 2 if reconstituted)",
    )
    parser.add_argument(
        "--keep-unlisted",
        action="store_true",
        help="Keep previously active tickers that are missing from the official page",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Apply even if the scrape looks incomplete (drop-only or odd count)",
    )
    args = parser.parse_args()

    print(f"Fetching holdings from {args.url} ...")
    scraped, as_of = scrape_holdings(args.url)
    existing = load_existing_rows(args.csv)
    diff = diff_holdings(existing, scraped)
    print(format_report(diff, as_of))
    assert_scrape_plausible(scraped, diff, force=args.force)

    if args.check:
        return 2 if diff["rebalanceDetected"] else 0

    merged = merge_official_holdings(
        scraped, existing, keep_unlisted=args.keep_unlisted
    )
    write_holdings_csv(args.csv, merged)
    write_holdings_meta(
        args.meta,
        build_holdings_meta(source_url=args.url, diff=diff, as_of=as_of),
    )
    active = sum(1 for row in merged if str(row.get("active", "true")).lower() == "true")
    print(f"Wrote {len(merged)} rows ({active} active) -> {args.csv}")
    print(f"Wrote holdings sync meta -> {args.meta}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
