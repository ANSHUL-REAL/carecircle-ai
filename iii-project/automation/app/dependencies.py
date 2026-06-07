import os
from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException, status

from app.auth import AuthError, Principal, validate_token
from app.messaging import Messenger, SesMessenger, SimulationMessenger, SnsMessenger
from app.repositories import CaseRepository, DynamoRepository


def get_clock() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def get_repository() -> CaseRepository:
    return DynamoRepository(clock=get_clock)


def get_outreach_mode() -> str:
    return os.getenv("OUTREACH_MODE", "simulation")


def get_messenger(
    mode: str = Depends(get_outreach_mode),
) -> Messenger:
    if mode == "simulation":
        return SimulationMessenger()
    if mode == "sms":
        return SnsMessenger()
    return SesMessenger()


def get_principal(
    authorization: str | None = Header(default=None),
) -> Principal:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
        )
    secret = os.getenv("AUTH_SECRET")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_SECRET is not configured",
        )
    try:
        return validate_token(authorization.removeprefix("Bearer ").strip(), secret)
    except AuthError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error


def require_operator(
    principal: Principal = Depends(get_principal),
) -> Principal:
    if principal.role not in {"admin", "volunteer"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin or volunteer role required",
        )
    return principal


def require_admin(
    principal: Principal = Depends(get_principal),
) -> Principal:
    if principal.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin role required",
        )
    return principal
