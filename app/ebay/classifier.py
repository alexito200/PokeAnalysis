"""Classify Pokemon card listings returned by eBay.

This module deliberately separates *listing classification* from *card identity
matching*.  The classifier answers questions such as:

- Is this a single-card listing we can use?
- Is it RAW, PSA graded, another grading company, or unusable?
- If graded, what company and grade are present?
- If RAW, can we infer a condition from the title?
- What card-number/year/language/variant signals are present for the future
  catalog/search matcher?

The future search/catalog layer should decide whether a listing actually belongs
to the canonical card selected by the user (set, card number, language, printing,
etc.).  Keeping those responsibilities separate prevents title heuristics from
becoming the source of truth for card identity.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


CLASS_RAW = "RAW"
CLASS_PSA = "PSA"
CLASS_OTHER_GRADED = "OTHER_GRADED"
CLASS_REJECTED = "REJECTED"

RAW_CONDITIONS = ("NM", "LP", "MP", "HP", "DMG", "UNKNOWN")

# Terms that strongly indicate that the listing should not be used as a normal
# single-card market comp.  These are intentionally conservative: variant terms
# such as "shadowless", "1st edition", "reprint", or "jumbo" are recorded as
# signals instead of being rejected here because those may be legitimate cards
# when the user's canonical-card selection explicitly calls for them.
HARD_REJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("multi_card_lot", re.compile(r"\b(?:card\s+)?lot\b|\blot\s+of\b", re.I)),
    ("multi_card_bundle", re.compile(r"\bbundle\b|\bbig\s+(?:3|three)\b", re.I)),
    ("complete_set", re.compile(r"\b(?:complete|master)\s+set\b", re.I)),
    (
        "multiple_cards",
        re.compile(
            r"\b(?:2|3|4|5|6|7|8|9|10|two|three|four|five|six|seven|eight|nine|ten)\s*"
            r"(?:x\s*)?(?:pokemon\s+)?cards?\b",
            re.I,
        ),
    ),
    ("you_pick_listing", re.compile(r"\b(?:you\s+pick|pick\s+your|choose\s+your)\b", re.I)),
    (
        "sealed_product",
        re.compile(
            r"\b(?:booster\s+(?:pack|box)|elite\s+trainer\s+box|ETB|mystery\s+(?:pack|box))\b",
            re.I,
        ),
    ),
    (
        "altered_or_restored",
        re.compile(r"\b(?:restored|rebacked|recolored|trimmed|altered)\b", re.I),
    ),
    (
        "proxy_or_replica",
        re.compile(r"\b(?:proxy|replica|counterfeit|facsimile|orica)\b", re.I),
    ),
    (
        "custom_card",
        re.compile(r"\b(?:custom|fan[ -]?made)\s+(?:pokemon\s+)?card\b", re.I),
    ),
)

# Marketing language sometimes puts "PSA 10" in an ungraded listing title even
# though the card is not actually slabbed.  These phrases prevent those listings
# from being misclassified as graded comps.
SPECULATIVE_GRADING_RE = re.compile(
    r"(?:\b(?:PSA|CGC|BGS|SGC|TAG)\s*(?:10|[1-9](?:\.5)?)\s*"
    r"(?:candidate|potential|worthy|ready|quality|contender|possible|\?)\b)"
    r"|(?:\b(?:candidate|potential|worthy|ready|contender)\s+(?:for\s+)?"
    r"(?:PSA|CGC|BGS|SGC|TAG)\s*(?:10|[1-9](?:\.5)?)\b)",
    re.I,
)

GRADER_ALIASES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PSA", re.compile(r"\b(?:PSA|Professional\s+Sports\s+Authenticator)\b", re.I)),
    ("CGC", re.compile(r"\bCGC\b", re.I)),
    ("BGS", re.compile(r"\b(?:BGS|Beckett)\b", re.I)),
    ("SGC", re.compile(r"\bSGC\b", re.I)),
    ("TAG", re.compile(r"\bTAG\b", re.I)),
    ("ACE", re.compile(r"\bACE\s+Grading\b", re.I)),
)

GRADE_TOKEN = r"(10(?:\.0)?|[1-9](?:\.5|\.0)?)"
GRADE_LABEL_WORDS = (
    r"(?:GEM\s*MT|GEM\s*MINT|MINT|NM[ -]?MT|NEAR\s*MINT|EX[ -]?MT|EXCELLENT|"
    r"VG[ -]?EX|VERY\s*GOOD|GOOD|FAIR|POOR|PR)"
)

RAW_CONDITION_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "DMG",
        (
            re.compile(r"\bDMG\b", re.I),
            re.compile(r"\bDAMAGED\b", re.I),
            re.compile(r"\bHEAVILY\s+DAMAGED\b", re.I),
        ),
    ),
    (
        "HP",
        (
            re.compile(r"\bHP\b", re.I),
            re.compile(r"\bHEAVILY\s+PLAYED\b", re.I),
        ),
    ),
    (
        "MP",
        (
            re.compile(r"\bMP\b", re.I),
            re.compile(r"\bMODERATELY\s+PLAYED\b", re.I),
        ),
    ),
    (
        "LP",
        (
            re.compile(r"\bLP\b", re.I),
            re.compile(r"\bLIGHTLY\s+PLAYED\b", re.I),
        ),
    ),
    (
        "NM",
        (
            re.compile(r"\bNM\b", re.I),
            re.compile(r"\bNEAR\s+MINT\b", re.I),
            re.compile(r"\bMINT\b", re.I),
        ),
    ),
)

LANGUAGE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("English", re.compile(r"\bEnglish\b", re.I)),
    ("Japanese", re.compile(r"\bJapanese\b|\bJapan\b", re.I)),
    ("Korean", re.compile(r"\bKorean\b", re.I)),
    ("Chinese", re.compile(r"\bChinese\b", re.I)),
    ("German", re.compile(r"\bGerman\b", re.I)),
    ("French", re.compile(r"\bFrench\b", re.I)),
    ("Spanish", re.compile(r"\bSpanish\b", re.I)),
    ("Italian", re.compile(r"\bItalian\b", re.I)),
    ("Portuguese", re.compile(r"\bPortuguese\b", re.I)),
)

VARIANT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("first_edition", re.compile(r"\b(?:1st|first)\s+edition\b", re.I)),
    ("shadowless", re.compile(r"\bshadowless\b", re.I)),
    ("unlimited", re.compile(r"\bunlimited\b", re.I)),
    ("reverse_holo", re.compile(r"\breverse\s+holo(?:foil)?\b", re.I)),
    ("non_holo", re.compile(r"\bnon[ -]?holo\b", re.I)),
    ("holo", re.compile(r"\bholo(?:foil)?\b", re.I)),
    ("promo", re.compile(r"\bpromo\b", re.I)),
    ("stamped", re.compile(r"\bstamped\b", re.I)),
    ("error", re.compile(r"\b(?:error|misprint)\b", re.I)),
    ("prerelease", re.compile(r"\bpre[ -]?release\b", re.I)),
    ("reprint", re.compile(r"\breprint\b|\breproduction\b", re.I)),
    ("jumbo", re.compile(r"\b(?:jumbo|oversized)\b", re.I)),
    ("metal", re.compile(r"\bmetal\b", re.I)),
    ("gold", re.compile(r"\bgold\b", re.I)),
)

CARD_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])#?([A-Za-z]{0,4}\d{1,4}[A-Za-z]?/[A-Za-z]{0,4}\d{1,4}[A-Za-z]?)(?![A-Za-z0-9])",
    re.I,
)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _repair_mojibake(value: str) -> str:
    """Repair common UTF-8-as-Latin-1 display corruption when it is obvious."""
    if not any(marker in value for marker in ("Ã", "Â", "â€", "â€™", "â€“")):
        return value

    try:
        repaired = value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value

    return repaired


def normalize_title(title: str | None) -> str:
    """Return a stable, accent-insensitive representation for title matching."""
    if not title:
        return ""

    value = _repair_mojibake(str(title))
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace("’", "'").replace("–", "-").replace("—", "-")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _extract_grade(title: str, grader: str) -> float | int | None:
    aliases = {
        "PSA": r"(?:PSA|Professional\s+Sports\s+Authenticator)",
        "CGC": r"CGC",
        "BGS": r"(?:BGS|Beckett)",
        "SGC": r"SGC",
        "TAG": r"TAG",
        "ACE": r"ACE(?:\s+Grading)?",
    }
    company = aliases[grader]

    patterns = (
        re.compile(rf"\b{company}\b\s*(?:GRADE\s*)?{GRADE_TOKEN}\b", re.I),
        re.compile(rf"\b{company}\b\s*{GRADE_LABEL_WORDS}\s*{GRADE_TOKEN}\b", re.I),
        re.compile(rf"\b{company}\b[^\d]{{0,18}}\bGRADE\s*{GRADE_TOKEN}\b", re.I),
    )

    for pattern in patterns:
        match = pattern.search(title)
        if not match:
            continue

        # GRADE_TOKEN is the final numeric capture in every pattern.
        raw_grade = match.groups()[-1]
        try:
            grade_value = float(raw_grade)
        except (TypeError, ValueError):
            continue

        if not 1 <= grade_value <= 10:
            continue

        if grade_value.is_integer():
            return int(grade_value)
        return grade_value

    return None


def _grader_from_title(title: str) -> str | None:
    for company, pattern in GRADER_ALIASES:
        if pattern.search(title):
            return company
    return None


def _raw_condition(title: str) -> str:
    for condition, patterns in RAW_CONDITION_PATTERNS:
        if any(pattern.search(title) for pattern in patterns):
            return condition
    return "UNKNOWN"


def _extract_signals(title: str) -> dict[str, Any]:
    years = list(dict.fromkeys(YEAR_RE.findall(title)))
    card_numbers = list(dict.fromkeys(match.upper() for match in CARD_NUMBER_RE.findall(title)))

    language = None
    for language_name, pattern in LANGUAGE_PATTERNS:
        if pattern.search(title):
            language = language_name
            break

    variants = [name for name, pattern in VARIANT_PATTERNS if pattern.search(title)]

    # reverse_holo includes the word holo, so avoid reporting both unless the
    # title separately indicates a normal holo variant as well.
    if "reverse_holo" in variants and "holo" in variants:
        variants.remove("holo")

    return {
        "years": years,
        "card_numbers": card_numbers,
        "language": language,
        "variant_flags": variants,
    }


def _rejection_reason(title: str) -> str | None:
    for reason, pattern in HARD_REJECTION_PATTERNS:
        if pattern.search(title):
            return reason
    return None


def _bucket(classification: str, company: str | None, grade: float | int | None) -> str:
    if classification == CLASS_RAW:
        return "RAW"
    if classification == CLASS_PSA:
        return f"PSA_{grade}" if grade is not None else "PSA_UNRESOLVED"
    if classification == CLASS_OTHER_GRADED:
        company_part = company or "UNKNOWN"
        grade_part = str(grade) if grade is not None else "UNRESOLVED"
        return f"OTHER_GRADED_{company_part}_{grade_part}"
    return "REJECTED"


def classify_listing(
    title: str | None,
    ebay_condition: str | None = None,
) -> dict[str, Any]:
    """Classify one eBay listing for downstream Pokemon pricing analysis.

    `include` means the record is a usable single-card marketplace observation.
    The analytics layer must still select the appropriate bucket (for example,
    PSA-only multiplier calculations should ignore OTHER_GRADED listings).
    """
    normalized = normalize_title(title)
    condition = (ebay_condition or "").strip()
    condition_lower = condition.lower()
    signals = _extract_signals(normalized)
    reasons: list[str] = []

    rejection = _rejection_reason(normalized)
    if rejection:
        reasons.append(rejection)
        return {
            "classification": CLASS_REJECTED,
            "analytics_bucket": "REJECTED",
            "include": False,
            "needs_review": False,
            "grading_company": None,
            "grade": None,
            "raw_condition": None,
            "confidence": 0.99,
            "reasons": reasons,
            "signals": signals,
        }

    grader = _grader_from_title(normalized)
    speculative = bool(SPECULATIVE_GRADING_RE.search(normalized))
    ebay_says_graded = condition_lower == "graded"
    ebay_says_ungraded = condition_lower == "ungraded"

    # If eBay explicitly says Ungraded and the title uses grading language only
    # as marketing speculation, treat the card as RAW instead of PSA/CGC/etc.
    if grader and speculative and not ebay_says_graded:
        raw_condition = _raw_condition(normalized)
        reasons.append("speculative_grading_language")
        if raw_condition != "UNKNOWN":
            reasons.append(f"raw_condition_{raw_condition.lower()}")

        confidence = 0.96 if ebay_says_ungraded else 0.86
        return {
            "classification": CLASS_RAW,
            "analytics_bucket": "RAW",
            "include": True,
            "needs_review": not ebay_says_ungraded,
            "grading_company": None,
            "grade": None,
            "raw_condition": raw_condition,
            "confidence": confidence,
            "reasons": reasons,
            "signals": signals,
        }

    if grader:
        grade = _extract_grade(normalized, grader)
        classification = CLASS_PSA if grader == "PSA" else CLASS_OTHER_GRADED
        reasons.append(f"grader_{grader.lower()}")

        if grade is not None:
            reasons.append(f"grade_{grade}")
            confidence = 0.99 if ebay_says_graded else 0.96
            needs_review = False
            include = True
        else:
            reasons.append("grade_not_resolved")
            confidence = 0.86 if ebay_says_graded else 0.72
            needs_review = True
            # A graded comp without a grade cannot be used in a grade-specific
            # multiplier until it is manually resolved.
            include = False

        return {
            "classification": classification,
            "analytics_bucket": _bucket(classification, grader, grade),
            "include": include,
            "needs_review": needs_review,
            "grading_company": grader,
            "grade": grade,
            "raw_condition": None,
            "confidence": confidence,
            "reasons": reasons,
            "signals": signals,
        }

    # If eBay itself says Graded, retain the record as an unresolved third-party
    # graded listing instead of incorrectly treating it as RAW.
    title_says_graded = bool(re.search(r"\b(?:graded|slabbed|slab)\b", normalized, re.I))
    if ebay_says_graded or title_says_graded:
        reasons.append("graded_but_company_unresolved")
        return {
            "classification": CLASS_OTHER_GRADED,
            "analytics_bucket": "OTHER_GRADED_UNKNOWN_UNRESOLVED",
            "include": False,
            "needs_review": True,
            "grading_company": None,
            "grade": None,
            "raw_condition": None,
            "confidence": 0.62 if ebay_says_graded else 0.55,
            "reasons": reasons,
            "signals": signals,
        }

    raw_condition = _raw_condition(normalized)
    if raw_condition != "UNKNOWN":
        reasons.append(f"raw_condition_{raw_condition.lower()}")

    if ebay_says_ungraded:
        confidence = 0.97
        reasons.append("ebay_condition_ungraded")
    elif condition_lower in {"new", "used", "pre-owned", "preowned"}:
        # eBay condition labels can be noisy for trading cards.  Absence of a
        # grading company is more useful than treating "New" as card condition.
        confidence = 0.84
        reasons.append("ebay_condition_not_card_specific")
    else:
        confidence = 0.80
        reasons.append("no_grading_company_detected")

    # Reprint/jumbo/metal/gold are legitimate variants in some Pokemon products,
    # but should not silently contaminate another printing's pricing.  Keep them
    # usable while marking them for the canonical-card matcher to verify.
    review_variant_flags = {"reprint", "jumbo", "metal", "gold"}
    needs_review = bool(review_variant_flags.intersection(signals["variant_flags"]))
    if needs_review:
        reasons.append("variant_requires_card_match")
        confidence = min(confidence, 0.76)

    return {
        "classification": CLASS_RAW,
        "analytics_bucket": "RAW",
        "include": True,
        "needs_review": needs_review,
        "grading_company": None,
        "grade": None,
        "raw_condition": raw_condition,
        "confidence": confidence,
        "reasons": reasons,
        "signals": signals,
    }
