"""Minimal eBay Browse API integration for PokeAnalysis."""

from __future__ import annotations

import logging
from typing import Any

import requests
from fastapi import APIRouter, Header, HTTPException, Query

from app.ebay.auth import EbayOAuthError, _require_admin_key, get_application_token
from app.ebay.classifier import classify_listing


EBAY_BROWSE_SEARCH_URL = (
    "https://api.ebay.com/buy/browse/v1/item_summary/search"
)

# PokeAnalysis intentionally focuses graded analytics on 8, 9, and 10 only.
# The classifier can still identify other grades, but they are excluded from
# downstream pricing calculations and user-facing graded market analytics.
SUPPORTED_GRADED_GRADES = {8, 9, 10}

logger = logging.getLogger("pokeanalysis.ebay.browse")

router = APIRouter(prefix="/api/ebay", tags=["eBay Browse"])


class EbayBrowseError(RuntimeError):
    """Raised when a Browse API request fails."""


def _money(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None

    amount = value.get("value")
    currency = value.get("currency")
    if amount is None or currency is None:
        return None

    return {"value": str(amount), "currency": str(currency)}


def _classifier_error_result(exc: Exception) -> dict[str, Any]:
    """Return a safe fallback so one unusual eBay listing cannot break a search."""
    return {
        "classification": "REJECTED",
        "analytics_bucket": "CLASSIFIER_ERROR",
        "include": False,
        "needs_review": True,
        "grading_company": None,
        "grade": None,
        "grade_supported": None,
        "raw_condition": None,
        "confidence": 0.0,
        "reasons": ["classifier_error", type(exc).__name__],
        "signals": {
            "years": [],
            "card_numbers": [],
            "language": None,
            "variant_flags": [],
        },
    }


def _apply_grade_focus(classification: dict[str, Any]) -> dict[str, Any]:
    """Exclude graded listings outside the supported 8/9/10 analytics range.

    We intentionally leave RAW records unchanged. Graded records below 8 or
    unresolved/half grades remain classified for diagnostics, but they cannot
    enter price averages, multipliers, charts, or recent-sale analytics.
    """
    result = dict(classification)
    result["reasons"] = list(classification.get("reasons", []))

    classification_name = result.get("classification")
    if classification_name not in {"PSA", "OTHER_GRADED"}:
        result["grade_supported"] = None
        return result

    grade = result.get("grade")
    grade_supported = grade in SUPPORTED_GRADED_GRADES
    result["grade_supported"] = grade_supported

    if not grade_supported:
        result["include"] = False
        if "grade_outside_supported_range" not in result["reasons"]:
            result["reasons"].append("grade_outside_supported_range")

    return result


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    image = item.get("image") if isinstance(item.get("image"), dict) else {}
    title = item.get("title")
    condition = item.get("condition")

    try:
        classification = classify_listing(
            title=title,
            ebay_condition=condition,
        )
        classification = _apply_grade_focus(classification)
    except Exception as exc:
        # A marketplace title can contain unexpected values. Do not let one bad
        # listing take down the entire search response; mark it for review and
        # record the exception type in Render logs without exposing secrets.
        logger.exception(
            "Classifier failed for eBay item_id=%s legacy_item_id=%s",
            item.get("itemId"),
            item.get("legacyItemId"),
        )
        classification = _classifier_error_result(exc)

    return {
        "item_id": item.get("itemId"),
        "legacy_item_id": item.get("legacyItemId"),
        "title": title,
        "price": _money(item.get("price")),
        "condition": condition,
        "buying_options": item.get("buyingOptions", []),
        "image_url": image.get("imageUrl"),
        "item_web_url": item.get("itemWebUrl"),
        "listing_marketplace_id": item.get("listingMarketplaceId"),
        "classification": classification,
    }


def search_items(
    query: str,
    limit: int = 20,
    marketplace_id: str = "EBAY_US",
) -> dict[str, Any]:
    """Search active eBay listings using the Production Browse API."""
    try:
        token = get_application_token()
    except EbayOAuthError as exc:
        raise EbayBrowseError(str(exc)) from exc

    try:
        response = requests.get(
            EBAY_BROWSE_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token.access_token}",
                "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
                "Accept": "application/json",
            },
            params={
                "q": query,
                "limit": limit,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise EbayBrowseError(f"Could not reach eBay Browse API: {exc}") from exc

    if response.status_code != 200:
        try:
            body = response.json()
        except ValueError:
            body = None

        message = "eBay rejected the Browse API request."
        if isinstance(body, dict):
            errors = body.get("errors")
            if isinstance(errors, list) and errors:
                first_error = errors[0]
                if isinstance(first_error, dict):
                    message = str(
                        first_error.get("longMessage")
                        or first_error.get("message")
                        or message
                    )

        raise EbayBrowseError(
            f"eBay Browse API failed ({response.status_code}): {message}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise EbayBrowseError("eBay returned an invalid JSON response.") from exc

    summaries = payload.get("itemSummaries", [])
    if not isinstance(summaries, list):
        summaries = []

    normalized_items = [
        _normalize_item(item)
        for item in summaries
        if isinstance(item, dict)
    ]

    classification_counts: dict[str, int] = {}
    for item in normalized_items:
        result = item.get("classification")
        if not isinstance(result, dict):
            continue
        bucket = str(result.get("analytics_bucket", "UNKNOWN"))
        classification_counts[bucket] = classification_counts.get(bucket, 0) + 1

    return {
        "query": query,
        "marketplace_id": marketplace_id,
        "total": payload.get("total", 0),
        "limit": payload.get("limit", limit),
        "offset": payload.get("offset", 0),
        "supported_graded_grades": sorted(SUPPORTED_GRADED_GRADES),
        "classification_counts": classification_counts,
        "items": normalized_items,
    }


@router.get("/search")
def ebay_search(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    marketplace_id: str = Query(default="EBAY_US", min_length=5, max_length=20),
    x_pokeanalysis_admin_key: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    Search active eBay listings and classify each result.

    This development endpoint is protected with the PokeAnalysis admin key to
    prevent public callers from consuming eBay API quota.
    """
    _require_admin_key(x_pokeanalysis_admin_key)

    try:
        return search_items(
            query=q,
            limit=limit,
            marketplace_id=marketplace_id,
        )
    except EbayBrowseError as exc:
        logger.exception("eBay Browse search failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
