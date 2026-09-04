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

# Market / guidance / operational negatives (weight 1) — not day-tape templates
SOFT_NEGATIVE = [
    r"\bbearish\b",
    r"\bmiss(?:es|ed) estimates?\b",
    r"\bmiss(?:es|ed) expectation",
    r"\bdisappoint(?:s|ed|ing)\b",
    r"\bguidance cut\b",
    r"\bcuts? guidance\b",
    r"\bprofit warning\b",
    r"\boutage\b",
    r"\bshutdown\b",
    r"\bsuspend(?:s|ed|ing)\b",
    r"\bdelay(?:s|ed)\b",
    r"\bshortage\b",
    r"\bfine(?:d|s)? by\b",
    r"\bpenalt(?:y|ies)\b",
    r"\bsettlement\b",
    r"\bcontroversy\b",
    r"\bcontroversial\b",
    r"\bfaces? delays?\b",
    r"\bfail(?:s|ed|ure)\b",
    r"\bdowngrade(?:s|d)?\b",
]

# Tape / price-move language — watch at most when that's all the title has
TAPE_MOVE = [
    r"\bplunge(?:s|d)?\b",
    r"\bcrash(?:es|ed)?\b",
    r"\btumble(?:s|d)?\b",
    r"\bslump(?:s|ed)?\b",
    r"\bdive(?:s|d)?\b",
    r"\bsell[- ]?off\b",
    r"\bstock(?:s)? (?:drop|drops|fall|falls|slide|slides|sink|sinks|plunge|plunges)\b",
    r"\b(?:drop|drops|fall|falls|slide|slides|sink|sinks|plunge|plunges)s?\s+(?:nearly\s+)?\d",
    r"\bshares?\s+(?:fall|falls|drop|drops|sink|sinks)\s+\d",
    r"\bunderperform(?:s|ed|ing)?\b",
]

# GlobeNewswire / plaintiff-mill SEO — not company-fundamental risk
LAWSUIT_MILL = [
    r"\bsecurities fraud investigation\b",
    r"\binvestigates?\b.{0,80}\b(?:over|regarding)\b.{0,60}\balleged\b",
    r"\bshareholder alert\b",
    r"\bclass action lawsuit investigation\b",
]

# Ownership / fund-flow noise — not company-fundamental negatives
NOISE_PATTERNS = [
    r"\b(?:cuts?|reduces?|lowers?|trims?|boosts?|raises?|increases?|buys?|sells?)\b.{0,40}\b(?:position|stake|holdings?|shares)\b",
    r"\b(?:position|stake|holdings?|shares)\b.{0,40}\b(?:cut|reduced|lowered|trimmed|boosted|raised|increased)\b",
    r"\bhas \$\S+ (?:stake|position)\b",
    r"\btakes? (?:a )?(?:bullish|bearish) stance\b",
    r"\bpurchases? new (?:position|holdings?)\b",
    r"\bdecreases? (?:its )?(?:position|stake|holdings?)\b",
    r"\bsold \$[\d.,]+\s*(?:million|billion|m)\s+shares\b",
    r"\bunderperforms?\s+(?:monday|tuesday|wednesday|thursday|friday|today|this week)\b",
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
    r"\brises?\b",
    r"\bgains?\b",
    r"\brelief\b",
]

_STRONG = [re.compile(p, re.I) for p in STRONG_NEGATIVE]
_SOFT = [re.compile(p, re.I) for p in SOFT_NEGATIVE]
_TAPE = [re.compile(p, re.I) for p in TAPE_MOVE]
_MILL = [re.compile(p, re.I) for p in LAWSUIT_MILL]
_NOISE = [re.compile(p, re.I) for p in NOISE_PATTERNS]
_POS = [re.compile(p, re.I) for p in POSITIVE_HINTS]


def is_lawsuit_mill(headline: str) -> bool:
    """True for plaintiff-firm / GlobeNewswire investigation mill headlines."""
    if not headline:
        return False
    return any(rx.search(headline) for rx in _MILL)


def is_tape_move(headline: str) -> bool:
    """True if the title is (or includes) a market tape-move phrase."""
    if not headline:
        return False
    return any(rx.search(headline) for rx in _TAPE)


def score_negative(headline: str) -> int:
    """Return a non-negative integer score; higher = more negative signals."""
    if not headline:
        return 0
    # Lawsuit-mill SEO first so stacked legal keywords cannot reach severe.
    if is_lawsuit_mill(headline):
        return 0
    if any(rx.search(headline) for rx in _NOISE):
        return 0

    strong_hits = sum(1 for rx in _STRONG if rx.search(headline))
    score = 2 * strong_hits
    score += sum(1 for rx in _SOFT if rx.search(headline))
    if is_tape_move(headline):
        score += 1
    if score and any(rx.search(headline) for rx in _POS):
        score = max(0, score - 1)
    # Pure tape move: watch at most, even if several price regexes overlap.
    if strong_hits == 0 and is_tape_move(headline):
        score = min(score, 1)
    return score


def is_negative(headline: str, threshold: int = 1) -> bool:
    return score_negative(headline) >= threshold
