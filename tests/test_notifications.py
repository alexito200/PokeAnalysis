import hashlib
import os

from fastapi.testclient import TestClient

from app.main import app, build_challenge_response


client = TestClient(app)


def test_hash_function_matches_sha256():
    challenge = "abc123"
    token = "A" * 32
    endpoint = "https://example.com/ebay/account-deletion"

    expected = hashlib.sha256(
        f"{challenge}{token}{endpoint}".encode("utf-8")
    ).hexdigest()

    assert build_challenge_response(challenge, token, endpoint) == expected


def test_get_challenge(monkeypatch):
    token = "A" * 32
    endpoint = "https://example.com/ebay/account-deletion"
    challenge = "challenge-123"

    monkeypatch.setenv("EBAY_VERIFICATION_TOKEN", token)
    monkeypatch.setenv("EBAY_NOTIFICATION_ENDPOINT_URL", endpoint)

    expected = hashlib.sha256(
        f"{challenge}{token}{endpoint}".encode("utf-8")
    ).hexdigest()

    response = client.get(
        "/ebay/account-deletion",
        params={"challenge_code": challenge},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"challengeResponse": expected}


def test_post_notification_acknowledged():
    payload = {
        "metadata": {
            "topic": "MARKETPLACE_ACCOUNT_DELETION",
            "schemaVersion": "1.0",
            "deprecated": False,
        },
        "notification": {
            "notificationId": "test-notification-id",
            "eventDate": "2026-08-19T12:00:00.000Z",
            "publishDate": "2026-08-19T12:00:01.000Z",
            "publishAttemptCount": 1,
            "data": {
                "username": "example-user",
                "userId": "example-user-id",
                "eiasToken": "example-eias-token",
            },
        },
    }

    response = client.post("/ebay/account-deletion", json=payload)

    assert response.status_code == 204
    assert response.content == b""


def test_rejects_wrong_topic():
    payload = {
        "metadata": {"topic": "SOMETHING_ELSE"},
        "notification": {"notificationId": "id-1"},
    }

    response = client.post("/ebay/account-deletion", json=payload)

    assert response.status_code == 400
