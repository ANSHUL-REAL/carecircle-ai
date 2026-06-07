import base64
import hashlib
import hmac
import json
import time

from pydantic import BaseModel, Field
from pydantic import ValidationError


class AuthError(Exception):
    pass


class Principal(BaseModel):
    email: str
    role: str
    display_name: str | None = Field(default=None, alias="displayName")
    linked_id: str | None = Field(default=None, alias="linkedId")


def validate_token(token: str, secret: str) -> Principal:
    try:
        encoded, signature = token.split(".", 1)
    except ValueError as error:
        raise AuthError("Malformed token") from error

    expected = _sign(encoded, secret)
    if not hmac.compare_digest(signature, expected):
        raise AuthError("Invalid token signature")

    try:
        payload = json.loads(_base64url_decode(encoded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as error:
        raise AuthError("Malformed token payload") from error

    try:
        exp = int(payload.get("exp") or 0)
    except (TypeError, ValueError) as error:
        raise AuthError("Malformed token payload") from error
    if exp <= int(time.time() * 1000):
        raise AuthError("Token expired")

    try:
        return Principal.model_validate(payload)
    except ValidationError as error:
        raise AuthError("Malformed token payload") from error


def sign_test_token(payload: dict, secret: str) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"{encoded}.{_sign(encoded, secret)}"


def _sign(encoded: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        encoded.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
