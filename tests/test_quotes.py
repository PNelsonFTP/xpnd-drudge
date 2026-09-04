"""Quote change math: prefer split-adjusted previous close."""

from __future__ import annotations

import unittest

from app.holdings import Holding
from app.stocks import compute_day_change, portfolio_stats


class QuoteChangeTests(unittest.TestCase):
    def test_prefers_adjusted_previous_close_over_raw_history(self) -> None:
        change, pct, outlier = compute_day_change(
            82.86,
            {"previousClose": 83.10, "chartPreviousClose": 83.10},
            [165.0, 164.2, 82.86],
        )
        self.assertLess(abs(pct), 1.0)
        self.assertFalse(outlier)
        self.assertAlmostEqual(change, 82.86 - 83.10, places=2)

    def test_unadjusted_history_without_previous_close_is_flagged(self) -> None:
        _change, pct, outlier = compute_day_change(82.86, {}, [165.0, 82.86])
        self.assertTrue(outlier)
        self.assertLess(pct, -40)

    def test_portfolio_stats_exclude_outliers(self) -> None:
        holdings = [
            Holding("APH", "Amphenol", "", "", 2.73),
            Holding("AAPL", "Apple", "", "", 4.72),
        ]
        quotes = {
            "APH": {"changePct": -47.74, "outlier": True},
            "AAPL": {"changePct": 1.0, "outlier": False},
        }
        stats = portfolio_stats(holdings, quotes)
        self.assertEqual(stats["weightedChangePct"], 1.0)
        self.assertEqual(stats["gainers"], 1)
        self.assertEqual(stats["losers"], 0)
        self.assertEqual(stats["quoteOutliers"], 1)


if __name__ == "__main__":
    unittest.main()
