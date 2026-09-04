"""Unit tests for negative-headline scoring (stdlib unittest)."""

from __future__ import annotations

import unittest

from app.sentiment import is_lawsuit_mill, score_negative


class ScoreNegativeFalsePositives(unittest.TestCase):
    def test_lawsuit_mill_stays_low(self) -> None:
        titles = [
            "SHAREHOLDER ALERT: Pomerantz LLP announces securities fraud investigation",
            "Kaplan Fox Investigates Apple Over Alleged Securities Violations",
            "Class action lawsuit investigation announced for investors",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertTrue(is_lawsuit_mill(title))
                self.assertLessEqual(score_negative(title), 1)

    def test_antitrust_relief_is_not_elevated(self) -> None:
        score = score_negative("Chipmakers gain as antitrust relief lifts sector")
        self.assertLess(score, 2)

    def test_tape_move_is_watch_at_most(self) -> None:
        self.assertLessEqual(score_negative("Apple stock falls 4%"), 1)
        self.assertLessEqual(
            score_negative(
                "Apple underperforms Thursday when compared to competitors"
            ),
            1,
        )
        self.assertLessEqual(
            score_negative("Apple sell-off may be running out of steam"),
            1,
        )


class ScoreNegativeRealRisk(unittest.TestCase):
    def test_layoff_breach_sued_stay_strong(self) -> None:
        self.assertGreaterEqual(
            score_negative("Apple announces layoffs of 2,000 employees"), 2
        )
        self.assertGreaterEqual(
            score_negative("Microsoft discloses data breach affecting customers"), 2
        )
        self.assertGreaterEqual(score_negative("Nvidia sued by customers"), 2)


class ScoreNegativeNoise(unittest.TestCase):
    def test_ownership_wallpaper_is_zero(self) -> None:
        self.assertEqual(
            score_negative("Fund Purchases New Position in Microsoft"), 0
        )
        self.assertEqual(score_negative("Blackrock Decreases Position in Nvidia"), 0)
        self.assertEqual(score_negative("Insider sold $5 million shares"), 0)


if __name__ == "__main__":
    unittest.main()
