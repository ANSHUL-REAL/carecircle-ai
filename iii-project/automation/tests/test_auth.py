import time

import pytest

from app.auth import AuthError, _sign, sign_test_token, validate_token


def test_valid_token_returns_role_and_email() -> None:
    token = sign_test_token(
        {
            "email": "admin@example.com",
            "role": "admin",
            "displayName": "Admin User",
            "linkedId": "ADM-1",
            "exp": int(time.time() * 1000) + 60_000,
        },
        "test-secret",
    )

    principal = validate_token(token, "test-secret")

    assert principal.email == "admin@example.com"
    assert principal.role == "admin"
    assert principal.display_name == "Admin User"
    assert principal.linked_id == "ADM-1"


def test_invalid_signature_is_rejected() -> None:
    token = sign_test_token(
        {
            "email": "admin@example.com",
            "role": "admin",
            "exp": int(time.time() * 1000) + 60_000,
        },
        "test-secret",
    )

    with pytest.raises(AuthError, match="Invalid token signature"):
        validate_token(token, "wrong-secret")


def test_expired_token_is_rejected() -> None:
    token = sign_test_token(
        {
            "email": "admin@example.com",
            "role": "admin",
            "exp": int(time.time() * 1000) - 1,
        },
        "test-secret",
    )

    with pytest.raises(AuthError, match="expired"):
        validate_token(token, "test-secret")


def test_malformed_token_is_rejected() -> None:
    with pytest.raises(AuthError, match="Malformed"):
        validate_token("not-a-session-token", "test-secret")


def test_invalid_exp_type_is_reported_as_auth_error() -> None:
    token = sign_test_token(
        {"email": "admin@example.com", "role": "admin", "exp": "abc"},
        "test-secret",
    )

    with pytest.raises(AuthError, match="Malformed token payload"):
        validate_token(token, "test-secret")


def test_missing_required_payload_fields_are_auth_errors() -> None:
    token = sign_test_token(
        {"email": "admin@example.com", "exp": int(time.time() * 1000) + 60_000},
        "test-secret",
    )

    with pytest.raises(AuthError, match="Malformed token payload"):
        validate_token(token, "test-secret")


def test_malformed_base64_payload_is_auth_error() -> None:
    encoded = "!!!!"
    with pytest.raises(AuthError, match="Malformed token payload"):
        validate_token(f"{encoded}.{_sign(encoded, 'test-secret')}", "test-secret")
