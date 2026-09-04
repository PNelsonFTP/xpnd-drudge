"""Load and manage portfolio holdings from CSV."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "holdings.csv"
DEFAULT_META = Path(__file__).resolve().parent.parent / "data" / "holdings_meta.json"

CSV_FIELDS = [
    "ticker",
    "company_name",
    "cusip",
    "classification",
    "weighting",
    "active",
]

# Bare ticker OR-clauses pollute Google News for short / common tokens.
AMBIGUOUS_TICKERS = {
    "ON",
    "APP",
    "UI",
    "MA",
    "V",
    "NOW",
    "GEN",
    "PATH",
    "AI",
    "OPEN",
    "BOX",
    "TEAM",
    "NET",
    "YOU",
    "ALL",
    "IT",
    "SO",
    "DO",
    "BE",
    "OR",
    "ANET",
    "FOXA",
    "FOX",
}

_ACTIVE_TRUE = {"1", "true", "yes", "y"}


@dataclass
class Holding:
    ticker: str
    company_name: str
    cusip: str
    classification: str
    weighting: float
    active: bool = True

    @property
    def clean_name(self) -> str:
        name = self.company_name
        for suf in (
            " Inc.",
            " Corp.",
            " Corporation",
            " Incorporated",
            " Co.",
            " Ltd.",
            " PLC",
            " plc",
        ):
            name = name.replace(suf, "")
        return re.sub(r"\s+", " ", name).strip(" ,")

    @property
    def search_query(self) -> str:
        """Google News query biased toward the company, not bare ticker words."""
        name = self.clean_name
        ticker = self.ticker
        if ticker in AMBIGUOUS_TICKERS or len(ticker) <= 2:
            return f'"{name}" stock'
        return f'"{name}" OR "{ticker}" stock'


def _is_active(value: object) -> bool:
    return str(value or "true").strip().lower() in _ACTIVE_TRUE


def load_holdings(path: Path | None = None, active_only: bool = True) -> list[Holding]:
    csv_path = path or DEFAULT_CSV
    holdings: list[Holding] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            active = _is_active(row.get("active", "true"))
            if active_only and not active:
                continue
            try:
                weight = float(row.get("weighting") or 0)
            except ValueError:
                weight = 0.0
            holdings.append(
                Holding(
                    ticker=row["ticker"].strip().upper(),
                    company_name=row["company_name"].strip(),
                    cusip=(row.get("cusip") or "").strip(),
                    classification=(row.get("classification") or "").strip(),
                    weighting=weight,
                    active=active,
                )
            )
    holdings.sort(key=lambda h: -h.weighting)
    return holdings


def load_existing_rows(path: Path | None = None) -> dict[str, dict]:
    csv_path = path or DEFAULT_CSV
    if not csv_path.exists():
        return {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        return {row["ticker"].strip().upper(): row for row in csv.DictReader(f)}


def write_holdings_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def load_holdings_meta(path: Path | None = None) -> dict:
    meta_path = path or DEFAULT_META
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_holdings_meta(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def diff_holdings(
    previous: dict[str, dict],
    scraped: list[dict],
    *,
    weight_threshold: float = 0.5,
) -> dict:
    """Compare last active universe to a fresh official scrape.

    Adds/removes are reconstitution. Weight-only moves at or above
    ``weight_threshold`` (percentage points) are reported as drift.
    """
    prev_active = {
        ticker: row
        for ticker, row in previous.items()
        if _is_active(row.get("active", "true"))
    }
    current = {row["ticker"].strip().upper(): row for row in scraped}
    added = sorted(set(current) - set(prev_active))
    removed = sorted(set(prev_active) - set(current))

    weight_changes: list[dict] = []
    for ticker, row in current.items():
        if ticker not in prev_active:
            continue
        try:
            old = float(prev_active[ticker].get("weighting") or 0)
            new = float(row.get("weighting") or 0)
        except ValueError:
            continue
        delta = round(new - old, 2)
        if abs(delta) >= weight_threshold:
            weight_changes.append(
                {"ticker": ticker, "from": old, "to": new, "delta": delta}
            )
    weight_changes.sort(key=lambda item: -abs(item["delta"]))

    return {
        "added": added,
        "removed": removed,
        "weightChanges": weight_changes,
        "rebalanceDetected": bool(added or removed),
        "previousCount": len(prev_active),
        "currentCount": len(current),
    }


def merge_official_holdings(
    scraped: list[dict],
    existing: dict[str, dict],
    *,
    keep_unlisted: bool = False,
) -> list[dict]:
    """Apply the official First Trust universe to the local CSV.

    Official names stay active unless the user already deactivated them.
    Names that left the fund are kept as inactive history, not as live
    news sections. ``keep_unlisted`` restores the old "manual extra" behavior.
    """
    scraped_tickers = {row["ticker"] for row in scraped}
    merged: list[dict] = []

    for row in scraped:
        prev = existing.get(row["ticker"])
        if prev and not _is_active(prev.get("active", "true")):
            row = {**row, "active": "false"}
        merged.append(row)

    for ticker, prev in existing.items():
        if ticker in scraped_tickers:
            continue
        if keep_unlisted and _is_active(prev.get("active", "true")):
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
            continue
        merged.append(
            {
                "ticker": ticker,
                "company_name": prev.get("company_name", ticker),
                "cusip": prev.get("cusip", ""),
                "classification": prev.get("classification", ""),
                "weighting": prev.get("weighting", "0"),
                "active": "false",
            }
        )

    def sort_key(row: dict) -> tuple[int, float]:
        try:
            weight = float(row.get("weighting") or 0)
        except ValueError:
            weight = 0.0
        return (0 if _is_active(row.get("active", "true")) else 1, -weight)

    merged.sort(key=sort_key)
    return merged


def assert_scrape_plausible(
    scraped: list[dict],
    diff: dict,
    *,
    force: bool = False,
    min_count: int = 40,
    max_count: int = 60,
    min_weight_sum: float = 90.0,
    max_weight_sum: float = 110.0,
    max_drop_only: int = 8,
) -> None:
    """Abort before deactivate-on-drop if the scrape looks incomplete."""
    if force:
        return
    count = len(scraped)
    if count < min_count or count > max_count:
        raise RuntimeError(
            f"Holdings scrape looked incomplete ({count} equity names; "
            f"expected {min_count}–{max_count})."
        )
    try:
        weight_sum = sum(float(row.get("weighting") or 0) for row in scraped)
    except ValueError as exc:
        raise RuntimeError("Holdings scrape had a non-numeric weight.") from exc
    if weight_sum < min_weight_sum or weight_sum > max_weight_sum:
        raise RuntimeError(
            f"Holdings scrape weight sum {weight_sum:.2f}% is outside "
            f"{min_weight_sum}–{max_weight_sum}."
        )
    dropped = list(diff.get("removed") or [])
    added = list(diff.get("added") or [])
    if not added and len(dropped) >= max_drop_only:
        raise RuntimeError(
            f"Refusing a drop-only scrape ({len(dropped)} removed, 0 added). "
            "Looks like a partial table. Pass --force if this is intentional."
        )


def build_holdings_meta(
    *,
    source_url: str,
    diff: dict,
    as_of: str | None = None,
    synced_at: str | None = None,
) -> dict:
    stamp = synced_at or datetime.now(timezone.utc).isoformat()
    return {
        "sourceUrl": source_url,
        "syncedAt": stamp,
        "asOf": as_of,
        "equityCount": diff.get("currentCount", 0),
        "previousCount": diff.get("previousCount", 0),
        "added": diff.get("added") or [],
        "removed": diff.get("removed") or [],
        "weightChanges": diff.get("weightChanges") or [],
        "rebalanceDetected": bool(diff.get("rebalanceDetected")),
    }
