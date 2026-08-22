"""The authentication journey, end to end.

This is the critical flow for Phase 1: a phone number with no prior account must
be able to reach an authenticated `/users/me` in two requests, and the abuse paths
around it must be closed.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from matchly_shared.domain import OtpChallenge, RefreshToken, User
from matchly_shared.otp import MockOtpProvider

PHONE = "+212612345678"


def _request_code(client: TestClient, phone: str = PHONE):
    return client.post("/api/v1/auth/request-otp", json={"phone": phone})


# ── happy path ───────────────────────────────────────────────────────────
def test_new_phone_signs_up_and_reaches_me(client: TestClient, otp: MockOtpProvider) -> None:
    requested = _request_code(client)
    assert requested.status_code == 200
    assert otp.last_code_for(PHONE) == requested.json()["dev_code"]

    verified = client.post(
        "/api/v1/auth/verify-otp",
        json={"phone": PHONE, "code": requested.json()["dev_code"], "name": "Youssef"},
    )
    assert verified.status_code == 200, verified.text
    tokens = verified.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["user"]["name"] == "Youssef"
    assert tokens["user"]["phone"] == PHONE

    me = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["id"] == tokens["user"]["id"]


def test_local_format_reaches_the_same_account(client: TestClient) -> None:
    first = _request_code(client, "+212612345678")
    client.post(
        "/api/v1/auth/verify-otp",
        json={"phone": "+212612345678", "code": first.json()["dev_code"], "name": "Youssef"},
    )

    # Same person, typed the way a Moroccan player actually types it.
    second = _request_code(client, "0612345678")
    logged_in = client.post(
        "/api/v1/auth/verify-otp",
        json={"phone": "0612345678", "code": second.json()["dev_code"]},
    )

    assert logged_in.status_code == 200
    assert logged_in.json()["user"]["name"] == "Youssef"


def test_returning_player_keeps_their_profile(client: TestClient, db: Session) -> None:
    first = _request_code(client)
    client.post(
        "/api/v1/auth/verify-otp",
        json={"phone": PHONE, "code": first.json()["dev_code"], "name": "Youssef"},
    )
    second = _request_code(client)
    again = client.post(
        "/api/v1/auth/verify-otp",
        json={"phone": PHONE, "code": second.json()["dev_code"], "name": "Someone Else"},
    )

    # A second login must not rename an existing account.
    assert again.json()["user"]["name"] == "Youssef"
    assert db.scalar(select(User).where(User.phone == PHONE).exists().select())
    assert len(db.scalars(select(User).where(User.phone == PHONE)).all()) == 1


def test_phone_without_a_name_gets_a_usable_placeholder(client: TestClient) -> None:
    requested = _request_code(client)
    verified = client.post(
        "/api/v1/auth/verify-otp", json={"phone": PHONE, "code": requested.json()["dev_code"]}
    )
    assert verified.json()["user"]["name"] == "Player 5678"


# ── failure paths ────────────────────────────────────────────────────────
def test_wrong_code_is_rejected_and_counts_down(client: TestClient) -> None:
    _request_code(client)
    response = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": "000000"})

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "INVALID_OTP"
    assert error["details"]["attempts_remaining"] == 4


def test_code_cannot_be_replayed(client: TestClient) -> None:
    code = _request_code(client).json()["dev_code"]
    assert (
        client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": code}).status_code
        == 200
    )

    replayed = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": code})

    assert replayed.status_code == 400
    assert replayed.json()["error"]["code"] == "INVALID_OTP"


def test_brute_force_exhausts_the_challenge(client: TestClient) -> None:
    code = _request_code(client).json()["dev_code"]
    for _ in range(5):
        client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": "000000"})

    blocked = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": "000000"})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"

    # And the real code is dead too — the challenge is consumed, not just paused.
    assert (
        client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": code}).status_code
        == 400
    )


def test_expired_code_is_rejected(client: TestClient, db: Session) -> None:
    code = _request_code(client).json()["dev_code"]
    challenge = db.scalars(select(OtpChallenge).where(OtpChallenge.phone == PHONE)).one()
    challenge.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    db.commit()

    response = client.post("/api/v1/auth/verify-otp", json={"phone": PHONE, "code": code})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "OTP_EXPIRED"


def test_verifying_without_requesting_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/verify-otp", json={"phone": "+212611111111", "code": "123456"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_OTP"


def test_requests_are_rate_limited_per_number(client: TestClient) -> None:
    for _ in range(3):
        assert _request_code(client).status_code == 200

    limited = _request_code(client)

    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    # A different number is unaffected.
    assert _request_code(client, "+212699999999").status_code == 200


def test_invalid_phone_is_rejected_before_any_sms(client: TestClient, otp: MockOtpProvider) -> None:
    response = _request_code(client, "not-a-number")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PHONE"
    assert otp.sent == []


def test_response_never_leaks_the_full_phone_number(client: TestClient) -> None:
    body = _request_code(client).json()
    assert body["phone"] != PHONE
    assert body["phone"].endswith("678")


def test_code_is_never_stored_in_clear(client: TestClient, db: Session) -> None:
    code = _request_code(client).json()["dev_code"]
    challenge = db.scalars(select(OtpChallenge).where(OtpChallenge.phone == PHONE)).one()

    assert code not in challenge.code_hash


# ── tokens ───────────────────────────────────────────────────────────────
def test_me_requires_a_token(client: TestClient) -> None:
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_garbage_token_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/users/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_refresh_rotates_and_invalidates_the_old_token(client: TestClient, auth) -> None:
    tokens = auth.login()

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != tokens["refresh_token"]

    # The consumed token must not work a second time.
    replayed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replayed.status_code == 401
    assert replayed.json()["error"]["code"] == "INVALID_TOKEN"


def test_refreshed_access_token_works(client: TestClient, auth) -> None:
    tokens = auth.login()
    refreshed = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    ).json()

    me = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {refreshed['access_token']}"}
    )
    assert me.status_code == 200


def test_logout_revokes_the_refresh_token(client: TestClient, auth) -> None:
    tokens = auth.login()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    logged_out = client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers
    )
    assert logged_out.status_code == 204

    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )


def test_refresh_tokens_are_stored_hashed(client: TestClient, auth, db: Session) -> None:
    tokens = auth.login()
    stored = db.scalars(select(RefreshToken)).all()

    assert len(stored) == 1
    assert stored[0].token_hash != tokens["refresh_token"]


# ── profile & deletion ───────────────────────────────────────────────────
def test_profile_update(client: TestClient, auth) -> None:
    headers = auth.headers()
    response = client.patch("/api/v1/users/me", json={"name": "Hamza"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["name"] == "Hamza"
    assert client.get("/api/v1/users/me", headers=headers).json()["name"] == "Hamza"


def test_account_deletion_anonymises_and_locks_out(client: TestClient, auth, db: Session) -> None:
    tokens = auth.login()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    user_id = tokens["user"]["id"]

    assert client.delete("/api/v1/users/me", headers=headers).status_code == 204

    # The token stops working immediately.
    assert client.get("/api/v1/users/me", headers=headers).status_code == 404

    db.expire_all()
    deleted = db.scalars(select(User).where(User.id == user_id)).one()
    assert deleted.deleted_at is not None
    assert PHONE not in deleted.phone
    assert len(deleted.phone) <= 20  # the column is varchar(20); SQLite would not catch this
    assert deleted.name == "Deleted player"

    # Sessions are revoked, so a stolen refresh token is useless too.
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 401
    )


def test_the_same_number_can_sign_up_again_after_deletion(client: TestClient, auth) -> None:
    headers = auth.headers()
    client.delete("/api/v1/users/me", headers=headers)

    fresh = auth.login(name="New Start")

    assert fresh["user"]["name"] == "New Start"
    assert fresh["user"]["phone"] == PHONE


# ── error envelope ───────────────────────────────────────────────────────
def test_validation_errors_use_the_standard_envelope(client: TestClient) -> None:
    response = client.post("/api/v1/auth/request-otp", json={})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["fields"][0]["field"] == "phone"
    assert error["request_id"]


def test_unknown_route_uses_the_standard_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
