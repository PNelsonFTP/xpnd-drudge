"""Lightweight negative-news keyword scoring for headlines."""

from __future__ import annotations

import re

# Strong risk / legal / operational negatives (weight 2)
STRONG_NEGATIVE = [
    r"\blawsuit\b",
    r"\bsued\b",
    r"\bsues\b",
    r"\bclass action\b",
    r"\binvestigation\b",
    r"\binvestigat(?:es|ed|ing)\b",
    r"\bfraud\b",
    r"\bscandal\b",
    r"\brecall(?:s|ed)?\b",
    r"\blayoff(?:s)?\b",
    r"\bjob cut(?:s)?\b",
    r"\bbankrupt(?:cy|cies)?\b",
    r"\bdefault(?:s|ed)?\b",
    r"\bantitrust\b",
    r"\bhack(?:ed|ing)?\b",
    r"\bbreach(?:es|ed)?\b",
    r"\bcyberattack\b",
    r"\bindict(?:s|ed|ment)?\b",
    r"\ballegation(?:s)?\b",
    r"\baccuse(?:s|d)?\b",
    r"\bwritedown\b",
    r"\bimpairment\b",
    r"\bSEC probe\b",
    r"\bDOJ\b",
    r"\bcrisis\b",
    r"\bdisaster\b",
]

# Market / guidance negatives (weight 1)
SOFT_NEGATIVE = [
    r"\bplunge(?:s|d)?\b",
    r"\bcrash(?:es|ed)?\b",
    r"\btumble(?:s|d)?\b",
    r"\bslump(?:s|ed)?\b",
    r"\bdive(?:s|d)?\b",
    r"\bsell[- ]?off\b",
    r"\bdowngrade(?:s|d)?\b",
    r"\bbearish\b",
    r"\bmiss(?:es|ed) estimates?\b",
    r"\bmiss(?:es|ed) expectation",
    r"\bdisappoint(?:s|ed|ing)\b",
    r"\bguidance cut\b",
    r"\bcuts? guidance\b",
    r"\bprofit warning\b",
    r"\bstock(?:s)? (?:drop|drops|fall|falls|slide|slides|sink|sinks)\b",
    r"\b(?:drop|drops|fall|falls|slide|slides|sink|sinks) \d",
    r"\boutage\b",
    r"\bshutdown\b",
    r"\bsuspend(?:s|ed|ing)\b",
    r"\bdelay(?:s|ed)\b",
    r"\bshortage\b",
    r"\bunderperform(?:s|ed|ing)?\b",
    r"\bfine(?:d|s)? by\b",
    r"\bpenalt(?:y|ies)\b",
    r"\bsettlement\b",
    r"\bcontroversy\b",
    r"\bcontroversial\b",
    r"\bfaces? delays?\b",
    r"\bfail(?:s|ed|ure)\b",
]

# Ownership / fund-flow noise — not company-fundamental negatives
NOISE_PATTERNS = [
    r"\b(?:cuts?|reduces?|lowers?|trims?|boosts?|raises?|increases?|buys?|sells?)\b.{0,40}\b(?:position|stake|holdings?|shares)\b",
    r"\b(?:position|stake|holdings?|shares)\b.{0,40}\b(?:cut|reduced|lowered|trimmed|boosted|raised|increased)\b",
    r"\bhas \$\S+ (?:stake|position)\b",
    r"\btakes? (?:a )?(?:bullish|bearish) stance\b",
]

POSITIVE_HINTS = [
    r"\bbeats?\b",
    r"\bsurges?\b",
    r"\braill?ies?\b",
    r"\bjumps?\b",
    r"\brecord high\b",
    r"\boutperform",
    r"\braises? guidance\b",
    r"\bupgraded?\b",
]

_STRONG = [re.compile(p, re.I) for p in STRONG_NEGATIVE]
_SOFT = [re.compile(p, re.I) for p in SOFT_NEGATIVE]
_NOISE = [re.compile(p, re.I) for p in NOISE_PATTERNS]
_POS = [re.compile(p, re.I) for p in POSITIVE_HINTS]


def score_negative(headline: str) -> int:
    """Return a non-negative integer score; higher = more negative signals."""
    if not headline:
        return 0
    if any(rx.search(headline) for rx in _NOISE):
        return 0

    score = 0
    score += 2 * sum(1 for rx in _STRONG if rx.search(headline))
    score += sum(1 for rx in _SOFT if rx.search(headline))
    if score and any(rx.search(headline) for rx in _POS):
        score = max(0, score - 1)
    return score


def is_negative(headline: str, threshold: int = 1) -> bool:
    return score_negative(headline) >= threshold
