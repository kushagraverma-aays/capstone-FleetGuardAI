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
from app.schemas.common import DemoAccount, DemoAccounts, ScopeInfo
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


ROLE_LABELS = {
    "manufacturer_admin": "Administrator",
    "customer_admin": "Fleet customer",
    "viewer": "Read-only viewer",
}

ROLE_DESCRIPTIONS = {
    "manufacturer_admin": (
        "Every customer's vehicles, and the only role that can author and "
        "deploy rules."
    ),
    "customer_admin": (
        "One organisation's vehicles only. Can acknowledge alerts and raise "
        "work orders; reads rules but cannot change them."
    ),
    "viewer": (
        "The same vehicles as the fleet customer, with every write action "
        "removed."
    ),
}


@router.get(
    "/demo-accounts",
    response_model=DemoAccounts,
    summary="The seeded sign-ins offered on the login screen",
)
def demo_accounts(db: DbSession) -> DemoAccounts:
    """The three fixtures from the seed script, for the demo's front door.

    404s once `AUTH_ENABLED` is true: handing out working credentials is only
    defensible while nothing is being protected, and the login screen falls
    back to a plain email and password form when this endpoint is not there.
    """
    if settings.AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo accounts are not available when authentication is enforced.",
        )

    users = db.execute(select(User).order_by(User.user_id)).scalars().all()
    customers = {c.customer_id: c.name for c in db.execute(select(Customer)).scalars()}

    return DemoAccounts(
        accounts=[
            DemoAccount(
                email=user.email,
                password=settings.DEMO_PASSWORD,
                full_name=user.full_name,
                role=user.role,
                role_label=ROLE_LABELS.get(user.role, user.role),
                description=ROLE_DESCRIPTIONS.get(user.role, ""),
                customer_id=user.customer_id,
                customer_name=customers.get(user.customer_id) if user.customer_id else None,
            )
            for user in users
        ],
        note=(
            "Seeded demo accounts. They exist because AUTH_ENABLED is false; "
            "with enforcement on, this endpoint is not served."
        ),
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
