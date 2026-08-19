"""Minimal eBay Browse API integration for PokeAnalysis."""

from __future__ import annotations

from typing import Any

import requests
from fastapi import APIRouter, Header, HTTPException, Query

from app.ebay.auth import EbayOAuthError, _require_admin_key, get_application_token


EBAY_BROWSE_SEARCH_URL = (
    "https://api.ebay.com/buy/browse/v1/item_summary/search"
)

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


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    image = item.get("image") if isinstance(item.get("image"), dict) else {}

    return {
        "item_id": item.get("itemId"),
        "legacy_item_id": item.get("legacyItemId"),
        "title": item.get("title"),
        "price": _money(item.get("price")),
        "condition": item.get("condition"),
        "buying_options": item.get("buyingOptions", []),
        "image_url": image.get("imageUrl"),
        "item_web_url": item.get("itemWebUrl"),
        "listing_marketplace_id": item.get("listingMarketplaceId"),
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

    payload = response.json()
    summaries = payload.get("itemSummaries", [])
    if not isinstance(summaries, list):
        summaries = []

    return {
        "query": query,
        "marketplace_id": marketplace_id,
        "total": payload.get("total", 0),
        "limit": payload.get("limit", limit),
        "offset": payload.get("offset", 0),
        "items": [
            _normalize_item(item)
            for item in summaries
            if isinstance(item, dict)
        ],
    }


@router.get("/search")
def ebay_search(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    marketplace_id: str = Query(default="EBAY_US", min_length=5, max_length=20),
    x_pokeanalysis_admin_key: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    Search active eBay listings.

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
        raise HTTPException(status_code=502, detail=str(exc)) from exc
