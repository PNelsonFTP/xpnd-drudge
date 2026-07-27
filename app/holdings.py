"""Load and manage portfolio holdings from CSV."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "holdings.csv"


@dataclass
class Holding:
    ticker: str
    company_name: str
    cusip: str
    classification: str
    weighting: float
    active: bool = True

    @property
    def search_query(self) -> str:
        # Prefer company name + ticker for better Google News relevance.
        name = self.company_name.replace(" Inc.", "").replace(" Corp.", "")
        name = name.replace(" Corporation", "").replace(" Incorporated", "")
        return f'"{name}" OR {self.ticker} stock'


def load_holdings(path: Path | None = None, active_only: bool = True) -> list[Holding]:
    csv_path = path or DEFAULT_CSV
    holdings: list[Holding] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            active = str(row.get("active", "true")).strip().lower() in {
                "1",
                "true",
                "yes",
                "y",
            }
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
