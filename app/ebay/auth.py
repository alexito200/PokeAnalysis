"""OAuth client-credentials flow for eBay Production APIs."""

from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass

import requests
from fastapi import APIRouter, Header, HTTPException


EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_BASE_SCOPE = "https://api.ebay.com/oauth/api_scope"
TOKEN_EXPIRY_SAFETY_SECONDS = 60

router = APIRouter(prefix="/api/ebay/oauth", tags=["eBay OAuth"])


class EbayOAuthError(RuntimeError):
    """Raised when eBay OAuth configuration or token minting fails."""


@dataclass(frozen=True)
class EbayApplicationToken:
    access_token: str
    token_type: str
    expires_in: int
    scope: str
    expires_at_monotonic: float

    @property
    def seconds_remaining(self) -> int:
        return max(0, int(self.expires_at_monotonic - time.monotonic()))


_token_lock = threading.Lock()
_cached_token: EbayApplicationToken | None = None


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise EbayOAuthError(f"{name} is not configured.")
    return value


def _mint_application_token() -> EbayApplicationToken:
    client_id = _required_env("EBAY_CLIENT_ID")
    client_secret = _required_env("EBAY_CLIENT_SECRET")

    try:
        response = requests.post(
            EBAY_TOKEN_URL,
            auth=(client_id, client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "scope": EBAY_BASE_SCOPE,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise EbayOAuthError(f"Could not reach eBay OAuth service: {exc}") from exc

    if response.status_code != 200:
        try:
            error_body = response.json()
            error_name = error_body.get("error", "oauth_error")
            error_description = error_body.get(
                "error_description", "eBay rejected the OAuth request."
            )
        except ValueError:
            error_name = "oauth_error"
            error_description = "eBay rejected the OAuth request."

        raise EbayOAuthError(
            f"eBay OAuth failed ({response.status_code} {error_name}): "
            f"{error_description}"
        )

    payload = response.json()
    access_token = payload.get("access_token")
    expires_in = int(payload.get("expires_in", 0))
    token_type = str(payload.get("token_type", "Bearer"))
    scope = str(payload.get("scope", EBAY_BASE_SCOPE))

    if not access_token or expires_in <= 0:
        raise EbayOAuthError("eBay returned an incomplete OAuth token response.")

    usable_lifetime = max(1, expires_in - TOKEN_EXPIRY_SAFETY_SECONDS)

    return EbayApplicationToken(
        access_token=access_token,
        token_type=token_type,
        expires_in=expires_in,
        scope=scope,
        expires_at_monotonic=time.monotonic() + usable_lifetime,
    )


def get_application_token(force_refresh: bool = False) -> EbayApplicationToken:
    """Return a cached eBay Application token, minting a new one when needed."""
    global _cached_token

    with _token_lock:
        if (
            not force_refresh
            and _cached_token is not None
            and _cached_token.seconds_remaining > 0
        ):
            return _cached_token

        _cached_token = _mint_application_token()
        return _cached_token


def _require_admin_key(provided_key: str | None) -> None:
    expected_key = _required_env("POKEANALYSIS_ADMIN_KEY")

    if not provided_key or not secrets.compare_digest(provided_key, expected_key):
        raise HTTPException(status_code=401, detail="Invalid admin key.")


@router.post("/check")
def check_ebay_oauth(
    x_pokeanalysis_admin_key: str | None = Header(default=None),
) -> dict[str, object]:
    """
    Verify Production OAuth without ever returning the access token.

    This route is protected because minting tokens consumes eBay OAuth quota.
    """
    try:
        _require_admin_key(x_pokeanalysis_admin_key)
        token = get_application_token(force_refresh=True)
    except HTTPException:
        raise
    except EbayOAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "status": "ok",
        "environment": "production",
        "token_type": token.token_type,
        "expires_in": token.expires_in,
        "scope": token.scope,
        "message": "eBay Production OAuth authentication succeeded.",
    }
