"""Login and identity (spec section 3).

Login works whether or not `AUTH_ENABLED` is set: the endpoint always issues a
real token against a real bcrypt hash. What the flag changes is whether the
rest of the API *requires* that token, which is what lets the demo run on the
scope switcher while the authentication path stays exercised rather than
theoretical.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentScope, DbSession
from app.models import Customer, User
from app.schemas.common import ScopeInfo
from app.schemas.fleet import LoginRequest, TokenResponse
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange email and password for a bearer token",
)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = db.execute(
        select(User).where(User.email == payload.email.strip().lower())
    ).scalars().first()

    # One message for both failures: telling an attacker that the address
    # exists is half the work done for them.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated.",
        )

    token = create_access_token(
        subject=user.email,
        claims={
            "user_id": user.user_id,
            "role": user.role,
            "customer_id": user.customer_id,
            "name": user.full_name,
        },
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in_minutes=settings.JWT_EXPIRE_MINUTES,
        role=user.role,
        customer_id=user.customer_id,
        full_name=user.full_name,
        email=user.email,
    )


@router.get(
    "/me",
    response_model=ScopeInfo,
    summary="The caller's identity and what they are allowed to see",
)
def me(scope: CurrentScope, db: DbSession) -> ScopeInfo:
    customer_name = None
    if scope.customer_id is not None:
        customer = db.get(Customer, scope.customer_id)
        customer_name = customer.name if customer else None

    return ScopeInfo(
        customer_id=scope.customer_id,
        customer_name=customer_name,
        role=scope.role,
        email=scope.email,
        full_name=scope.full_name,
        is_manufacturer=scope.is_manufacturer,
        can_write=scope.can_write,
        can_manage_rules=scope.can_manage_rules,
        auth_enabled=settings.AUTH_ENABLED,
    )
