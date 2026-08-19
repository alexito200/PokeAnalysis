# PokeAnalysis — eBay Marketplace Account Deletion Compliance

This is the minimal backend needed to satisfy eBay's Marketplace Account
Deletion/Closure notification subscription requirement for the PokeAnalysis
Production keyset.

It provides:

- `GET /ebay/account-deletion`
  - Receives eBay's `challenge_code`.
  - Returns the required SHA-256 `challengeResponse` as JSON.
- `POST /ebay/account-deletion`
  - Accepts `MARKETPLACE_ACCOUNT_DELETION` JSON notifications.
  - Immediately acknowledges valid notifications with HTTP `204 No Content`.
  - Does **not** persist eBay usernames, user IDs, EIAS tokens, or the raw payload.
- `GET /health`
  - Simple deployment health check.

Official eBay reference:
https://developer.ebay.com/develop/guides-v2/marketplace-user-account-deletion

## 1. Local setup

Requires Python 3.11+.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Generate a verification token:

```powershell
python scripts\generate_verification_token.py
```

Copy the generated value into `.env`:

```env
EBAY_VERIFICATION_TOKEN=your_generated_token
```

For local testing only, set:

```env
EBAY_NOTIFICATION_ENDPOINT_URL=http://localhost:8000/ebay/account-deletion
```

Start the app:

```powershell
uvicorn app.main:app --reload
```

Open:

```text
http://localhost:8000/health
```

You should receive:

```json
{"status":"ok"}
```

## 2. Run the automated tests

```powershell
pytest
```

All tests should pass.

## 3. Deploy to a public HTTPS host

eBay requires the notification endpoint to be publicly reachable over HTTPS.
The included `render.yaml` makes this project ready for Render, but the FastAPI
app can be deployed to any host that provides HTTPS.

After deployment, your endpoint will look like:

```text
https://YOUR-HOST/ebay/account-deletion
```

Set these two environment variables on the hosting service:

```env
EBAY_VERIFICATION_TOKEN=the_same_token_you_generated
EBAY_NOTIFICATION_ENDPOINT_URL=https://YOUR-HOST/ebay/account-deletion
```

### Critical

`EBAY_NOTIFICATION_ENDPOINT_URL` must match **exactly** what you enter into the
eBay Developer Portal because eBay includes that exact endpoint string in the
SHA-256 validation calculation.

For example, these are different:

```text
https://example.com/ebay/account-deletion
https://example.com/ebay/account-deletion/
```

Use one exact form everywhere.

## 4. Enter the values in eBay

In the eBay Developer Portal for your Production application:

1. Open the Marketplace Account Deletion / Alerts and Notifications setup.
2. Select Marketplace Account Deletion.
3. Enter your alert email and save it.
4. For Notification Endpoint URL, enter:

```text
https://YOUR-HOST/ebay/account-deletion
```

5. For Verification token, enter exactly the same value as:

```text
EBAY_VERIFICATION_TOKEN
```

6. Save.

eBay will immediately send a request similar to:

```text
GET /ebay/account-deletion?challenge_code=...
```

This application calculates:

```text
SHA256(challengeCode + verificationToken + endpointURL)
```

and returns:

```json
{
  "challengeResponse": "<sha256-hex-value>"
}
```

with `200 OK` and `Content-Type: application/json`.

## 5. Send eBay's test notification

After eBay accepts the endpoint challenge, use **Send Test Notification** in
the eBay Developer Portal.

The same endpoint supports `POST` and returns `204 No Content` for a valid
`MARKETPLACE_ACCOUNT_DELETION` notification.

At that point, the compliance endpoint is configured for the current
PokeAnalysis stage.

## Important future requirement

This service currently stores no eBay user data, so its account-deletion
processing hook has nothing to delete.

When PokeAnalysis begins storing eBay user data, the function
`process_account_deletion_notification()` in `app/main.py` must be replaced
with irreversible deletion logic for all stored data associated with the
identifiers supplied by eBay.

eBay also recommends verifying the `X-EBAY-SIGNATURE` on received
notifications. That verification should be added when the Production keyset is
active and the application begins processing/storing eBay user data.
