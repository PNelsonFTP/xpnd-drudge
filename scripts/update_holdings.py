#!/usr/bin/env python3
"""Scrape XPND ETF holdings from First Trust and update data/holdings.csv."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HOLDINGS_URL = (
    "https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Ticker=XPND"
)
DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "holdings.csv"
SKIP_TICKERS = {"$USD", "USD", "CASH"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"\s*\(Class [A-Z]\)\s*$", "", name, flags=re.I)
    name = name.replace(", Inc.", " Inc.").replace(", Inc", " Inc.")
    return name


def parse_weight(raw: str) -> str:
    return raw.replace("%", "").strip()


def scrape_holdings(url: str = HOLDINGS_URL) -> list[dict]:
    resp = requests.get(url, headers=HEADERS, timeout=45)
    resp.raise_for_status()
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
            # Skip non-ticker identifiers (cash rows, blanks)
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
    return rows


def load_existing(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {row["ticker"].upper(): row for row in csv.DictReader(f)}


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ticker",
        "company_name",
        "cusip",
        "classification",
        "weighting",
        "active",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def merge_holdings(scraped: list[dict], existing: dict[str, dict]) -> list[dict]:
    """Keep manually inactivated tickers off; preserve custom names if set."""
    scraped_tickers = {r["ticker"] for r in scraped}
    merged: list[dict] = []

    for row in scraped:
        prev = existing.get(row["ticker"])
        if prev and prev.get("active", "true").lower() == "false":
            # User deactivated this name — keep it inactive and skip news later.
            row = {**row, "active": "false"}
        if prev and prev.get("company_name") and prev.get("active") == "true":
            # Prefer freshly scraped names; CSV remains the editable source of truth.
            pass
        merged.append(row)

    # Keep any manually added tickers that were not on the scrape.
    for ticker, prev in existing.items():
        if ticker in scraped_tickers:
            continue
        if prev.get("active", "true").lower() == "true":
            merged.append(
                {
                    "ticker": ticker,
                    "company_name": prev.get("company_name", ticker),
                    "cusip": prev.get("cusip", ""),
                    "classification": prev.get("classification", "Manual"),
                    "weighting": prev.get("weighting", "0"),
                    "active": "true",
                }
            )

    merged.sort(key=lambda r: -float(r.get("weighting") or 0))
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Update XPND holdings CSV")
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help=f"Path to holdings CSV (default: {DEFAULT_CSV})",
    )
    parser.add_argument(
        "--url",
        default=HOLDINGS_URL,
        help="Holdings page URL",
    )
    args = parser.parse_args()

    print(f"Fetching holdings from {args.url} ...")
    scraped = scrape_holdings(args.url)
    existing = load_existing(args.csv)
    merged = merge_holdings(scraped, existing)
    write_csv(args.csv, merged)
    active = sum(1 for r in merged if r.get("active", "true").lower() == "true")
    print(f"Wrote {len(merged)} holdings ({active} active) -> {args.csv}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
