import hashlib
import logging
import os
import re
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from app.ebay.auth import router as ebay_oauth_router

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("pokeanalysis.ebay_compliance")

app = FastAPI(
    title="PokeAnalysis API",
    version="1.1.0",
    description=(
        "PokeAnalysis backend with eBay Marketplace Account Deletion compliance "
        "and eBay Production OAuth support."
    ),
)

app.include_router(ebay_oauth_router)

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,80}$")
EXPECTED_TOPIC = "MARKETPLACE_ACCOUNT_DELETION"


def get_verification_token() -> str:
    token = os.getenv("EBAY_VERIFICATION_TOKEN", "")
    if not token:
        raise RuntimeError(
            "EBAY_VERIFICATION_TOKEN is not configured."
        )
    if not TOKEN_PATTERN.fullmatch(token):
        raise RuntimeError(
            "EBAY_VERIFICATION_TOKEN must be 32-80 characters and contain "
            "only letters, numbers, underscores, and hyphens."
        )
    return token


def get_notification_endpoint_url() -> str:
    endpoint = os.getenv("EBAY_NOTIFICATION_ENDPOINT_URL", "").strip()
    if not endpoint:
        raise RuntimeError(
            "EBAY_NOTIFICATION_ENDPOINT_URL is not configured."
        )
    return endpoint


def build_challenge_response(
    challenge_code: str,
    verification_token: str,
    endpoint_url: str,
) -> str:
    """
    eBay requires SHA-256 over this exact concatenation:
        challengeCode + verificationToken + endpoint
    """
    value = f"{challenge_code}{verification_token}{endpoint_url}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def process_account_deletion_notification(payload: dict[str, Any]) -> None:
    """
    Compliance-only implementation.

    This minimal service intentionally stores no eBay user data, so there is
    currently no user record to delete here.

    When the main PokeAnalysis application begins storing eBay user data,
    replace this function with the application's irreversible deletion logic
    keyed by the identifiers in notification.data.
    """
    # Deliberately do not log username, userId, eiasToken, or the raw payload.
    notification = payload.get("notification") or {}
    notification_id = notification.get("notificationId")

    if notification_id:
        logger.info(
            "Accepted Marketplace Account Deletion notification id=%s",
            notification_id,
        )
    else:
        logger.info("Accepted Marketplace Account Deletion notification.")


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ebay/account-deletion")
async def ebay_account_deletion_challenge(
    challenge_code: str = Query(..., min_length=1),
) -> JSONResponse:
    """
    Respond to eBay's endpoint ownership challenge.

    The response must be:
      HTTP 200
      Content-Type: application/json
      {"challengeResponse": "<sha256 hex digest>"}
    """
    try:
        token = get_verification_token()
        endpoint_url = get_notification_endpoint_url()
    except RuntimeError as exc:
        logger.error("Compliance endpoint is not configured: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    challenge_response = build_challenge_response(
        challenge_code=challenge_code,
        verification_token=token,
        endpoint_url=endpoint_url,
    )

    return JSONResponse(
        status_code=200,
        content={"challengeResponse": challenge_response},
    )


@app.post("/ebay/account-deletion", status_code=204)
async def ebay_account_deletion_notification(request: Request) -> Response:
    """
    Receive and immediately acknowledge an eBay Marketplace Account Deletion
    notification.

    eBay accepts 200, 201, 202, or 204 for acknowledgment. This implementation
    returns 204 and persists none of the notification's personal identifiers.
    """
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Request body must be valid JSON.",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object.")

    metadata = payload.get("metadata")
    notification = payload.get("notification")

    if not isinstance(metadata, dict) or not isinstance(notification, dict):
        raise HTTPException(
            status_code=400,
            detail="Missing metadata or notification object.",
        )

    if metadata.get("topic") != EXPECTED_TOPIC:
        raise HTTPException(
            status_code=400,
            detail=f"Unexpected notification topic. Expected {EXPECTED_TOPIC}.",
        )

    if not notification.get("notificationId"):
        raise HTTPException(
            status_code=400,
            detail="Missing notification.notificationId.",
        )

    # eBay recommends verifying the X-EBAY-SIGNATURE after acknowledgment.
    # Signature verification is intentionally not required for initial endpoint
    # activation because the Production keyset is disabled until this compliance
    # subscription is completed. Add full signature verification when the main
    # application begins processing/storing eBay user data.
    process_account_deletion_notification(payload)

    return Response(status_code=204)
