"""Unit tests for official-universe merge and reconstitution detection."""

from __future__ import annotations

import unittest

from app.holdings import (
    Holding,
    assert_scrape_plausible,
    diff_holdings,
    merge_official_holdings,
)


def _row(ticker: str, weight: str, active: str = "true", name: str | None = None) -> dict:
    return {
        "ticker": ticker,
        "company_name": name or ticker,
        "cusip": "",
        "classification": "Software",
        "weighting": weight,
        "active": active,
    }


class HoldingsRebalanceTests(unittest.TestCase):
    def test_diff_detects_adds_and_drops(self) -> None:
        previous = {
            "TMUS": _row("TMUS", "2.84"),
            "AAPL": _row("AAPL", "5.19"),
        }
        scraped = [_row("AAPL", "4.72"), _row("MSFT", "4.58")]
        diff = diff_holdings(previous, scraped)
        self.assertEqual(diff["added"], ["MSFT"])
        self.assertEqual(diff["removed"], ["TMUS"])
        self.assertTrue(diff["rebalanceDetected"])
        self.assertEqual(diff["previousCount"], 2)
        self.assertEqual(diff["currentCount"], 2)

    def test_weight_only_move_is_not_a_rebalance(self) -> None:
        previous = {"AAPL": _row("AAPL", "5.19")}
        scraped = [_row("AAPL", "3.90")]
        diff = diff_holdings(previous, scraped)
        self.assertFalse(diff["rebalanceDetected"])
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])
        self.assertEqual(diff["weightChanges"][0]["ticker"], "AAPL")
        self.assertAlmostEqual(diff["weightChanges"][0]["delta"], -1.29)

    def test_inactive_history_is_not_treated_as_a_drop(self) -> None:
        previous = {
            "AAPL": _row("AAPL", "5.00"),
            "ROKU": _row("ROKU", "0.29", active="false"),
        }
        scraped = [_row("AAPL", "4.72")]
        diff = diff_holdings(previous, scraped)
        self.assertEqual(diff["removed"], [])
        self.assertFalse(diff["rebalanceDetected"])

    def test_merge_deactivates_dropped_names(self) -> None:
        existing = {
            "TMUS": _row("TMUS", "2.84", name="T-Mobile US Inc."),
            "AAPL": _row("AAPL", "5.19", name="Apple Inc."),
        }
        scraped = [_row("AAPL", "4.72", name="Apple Inc."), _row("MSFT", "4.58", name="Microsoft")]
        merged = merge_official_holdings(scraped, existing)
        by_ticker = {row["ticker"]: row for row in merged}
        self.assertEqual(by_ticker["AAPL"]["active"], "true")
        self.assertEqual(by_ticker["MSFT"]["active"], "true")
        self.assertEqual(by_ticker["TMUS"]["active"], "false")
        self.assertEqual(by_ticker["AAPL"]["weighting"], "4.72")

    def test_merge_preserves_user_deactivation(self) -> None:
        existing = {"AAPL": _row("AAPL", "5.19", active="false")}
        scraped = [_row("AAPL", "4.72")]
        merged = merge_official_holdings(scraped, existing)
        self.assertEqual(merged[0]["active"], "false")

    def test_keep_unlisted_preserves_manual_extras(self) -> None:
        existing = {
            "AAPL": _row("AAPL", "5.00"),
            "WATCH": _row("WATCH", "0", name="Manual Watch"),
        }
        scraped = [_row("AAPL", "4.72")]
        merged = merge_official_holdings(scraped, existing, keep_unlisted=True)
        by_ticker = {row["ticker"]: row for row in merged}
        self.assertEqual(by_ticker["WATCH"]["active"], "true")

    def test_ambiguous_tickers_avoid_bare_or_clause(self) -> None:
        now = Holding("NOW", "ServiceNow, Inc.", "", "Software", 2.26)
        gen = Holding("GEN", "Gen Digital Inc.", "", "Software", 0.26)
        aapl = Holding("AAPL", "Apple Inc.", "", "Hardware", 4.72)
        self.assertNotIn("OR", now.search_query)
        self.assertIn("ServiceNow", now.search_query)
        self.assertNotIn("OR", gen.search_query)
        self.assertIn('"Apple" OR "AAPL" stock', aapl.search_query)
        fox = Holding("FOXA", "Fox Corporation", "", "Media", 0.23)
        self.assertEqual(fox.clean_name, "Fox")
        self.assertNotIn("corporation", fox.name_tokens)

    def test_partial_drop_only_scrape_is_rejected(self) -> None:
        scraped = [_row(f"T{i:02d}", "2.00") for i in range(50)]
        previous = {row["ticker"]: row for row in scraped}
        previous["ORCL"] = _row("ORCL", "2.48")
        previous["TMUS"] = _row("TMUS", "2.84")
        previous["ADI"] = _row("ADI", "2.63")
        previous["SNPS"] = _row("SNPS", "1.04")
        previous["ROKU"] = _row("ROKU", "0.29")
        previous["TKO"] = _row("TKO", "0.24")
        previous["FOXA"] = _row("FOXA", "0.23")
        previous["PTC"] = _row("PTC", "0.23")
        previous["WMG"] = _row("WMG", "0.23")
        previous["RMBS"] = _row("RMBS", "0.18")
        diff = diff_holdings(previous, scraped)
        self.assertEqual(len(diff["removed"]), 10)
        self.assertEqual(diff["added"], [])
        with self.assertRaises(RuntimeError):
            assert_scrape_plausible(scraped, diff)

    def test_force_allows_odd_scrape(self) -> None:
        scraped = [_row("AAPL", "100")]
        diff = {"added": [], "removed": ["ORCL"] * 8, "rebalanceDetected": True}
        with self.assertRaises(RuntimeError):
            assert_scrape_plausible(scraped, diff)
        assert_scrape_plausible(scraped, diff, force=True)


if __name__ == "__main__":
    unittest.main()
