"""Unit tests for junk / low-value / relevance headline filters."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.holdings import Holding
from app.news import (
    Article,
    CompanyNews,
    group_articles,
    is_junk,
    is_low_value,
    news_coverage,
    title_relevant,
)


def _holding(ticker: str, name: str) -> Holding:
    return Holding(ticker, name, "", "", 1.0)


def _article(
    title: str,
    *,
    source: str = "Reuters",
    score: int = 0,
    ticker: str = "MSFT",
) -> Article:
    return Article(
        id=f"{ticker}-{source}-{score}",
        title=title,
        link=f"https://example.com/{source}",
        source=source,
        published=datetime.now(timezone.utc),
        published_display="now",
        negative=score >= 1,
        negative_score=score,
        severity="severe" if score >= 4 else "elevated" if score >= 2 else "watch" if score else "none",
        age_hours=1.0,
        ticker=ticker,
    )


class TitleRelevant(unittest.TestCase):
    def test_foxa_ensign_bleed_is_rejected(self) -> None:
        foxa = _holding("FOXA", "Fox Corporation")
        self.assertFalse(
            title_relevant("Kaplan Fox Investigates The Ensign Group", foxa)
        )

    def test_on_wall_street_bleed_is_rejected(self) -> None:
        on = _holding("ON", "ON Semiconductor Corporation")
        self.assertFalse(title_relevant("Stocks slip on Wall Street", on))

    def test_aapl_real_title_is_accepted(self) -> None:
        aapl = _holding("AAPL", "Apple Inc.")
        self.assertTrue(title_relevant("Apple reports record iPhone sales", aapl))
        self.assertTrue(title_relevant("AAPL beats quarterly estimates", aapl))

    def test_app_apple_store_bleed_is_rejected(self) -> None:
        app = _holding("APP", "Applovin Corp.")
        self.assertFalse(
            title_relevant("Apple stock Buy rating on App Store", app)
        )

    def test_msft_real_title_is_accepted(self) -> None:
        msft = _holding("MSFT", "Microsoft Corporation")
        self.assertTrue(
            title_relevant("Microsoft Azure outage hits enterprise customers", msft)
        )


class JunkFilters(unittest.TestCase):
    def test_pipe_delimited_quote_ticker_is_junk(self) -> None:
        title = "APP|Applovin Corp|Price:412.440|Chg%:+20.460"
        self.assertTrue(is_junk(title))

    def test_tokenized_fx_converter_is_junk(self) -> None:
        title = "Price Today | Live AAPL to GBP"
        self.assertTrue(is_junk(title))
        self.assertTrue(is_junk("Apple Tokenized Stock converter listing"))


class LowValueFilters(unittest.TestCase):
    def test_marketbeat_purchase_is_low_value(self) -> None:
        title = (
            "Qube Research & Technologies LTD Purchases New Position in "
            "Microsoft Corporation"
        )
        self.assertTrue(is_low_value(title))

    def test_marketbeat_investment_and_form4_are_low_value(self) -> None:
        self.assertTrue(
            is_low_value("Fund Makes New $5.2 Million Investment in Apple")
        )
        self.assertTrue(is_low_value("Blackrock Decreases Position in Nvidia"))
        self.assertTrue(is_low_value("CEO Sells $2 Million of Company Shares"))
        self.assertTrue(is_low_value("Form 4: Director sells 10,000 shares"))


class GroupArticles(unittest.TestCase):
    def test_does_not_inflate_primary_score(self) -> None:
        mild = _article(
            "Microsoft Azure outage hits Europe",
            source="Reuters",
            score=0,
        )
        harsh = _article(
            "Microsoft Azure outage hits Europe customers",
            source="Blog",
            score=4,
        )
        grouped = group_articles([mild, harsh])
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0].negative_score, 0)
        self.assertEqual(grouped[0].source, "Reuters")
        self.assertTrue(grouped[0].related)
        self.assertEqual(grouped[0].related[0].source, "Blog")


class NewsCoverage(unittest.TestCase):
    def test_missing_news_lists_tickers_with_zero_articles(self) -> None:
        empty = CompanyNews("AAPL", "Apple Inc.", "Tech", 4.72, articles=[])
        covered = CompanyNews(
            "MSFT",
            "Microsoft Corporation",
            "Software",
            4.58,
            articles=[_article("Microsoft reports earnings", ticker="MSFT")],
        )
        cov = news_coverage([empty, covered])
        self.assertIn("AAPL", cov["missingNews"])
        self.assertNotIn("MSFT", cov["missingNews"])
        self.assertEqual(cov["articleCount"], 1)
        self.assertIn("feedFailures", cov)
        self.assertIn("emptyFeeds", cov)


if __name__ == "__main__":
    unittest.main()
