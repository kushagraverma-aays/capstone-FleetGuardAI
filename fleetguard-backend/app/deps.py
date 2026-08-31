"""Request dependencies: scope resolution, pagination, and write guards.

`get_current_scope()` is the single place where an HTTP request turns into a
tenant boundary. Spec section 3 requires that **the route code is identical
whether authentication is on or off** - only this dependency changes
behaviour.

A presented bearer token always drives access. `AUTH_ENABLED` decides only
what happens when there is no token:

  no token,  AUTH_ENABLED=false   the `X-Customer-Scope` header drives access,
                                  which is what the UI's scope switcher sets.
  no token,  AUTH_ENABLED=true    401.
  token,     either               the JWT drives role and tenant; the header
                                  may only *narrow* a manufacturer session,
                                  never widen a customer one.

Honouring a token even while enforcement is off is what makes the sign-in
screen mean something during the demo: signing in as the read-only viewer
genuinely takes write actions away, and turning `AUTH_ENABLED` on later changes
nothing a user can see. It gives away no security, because with the flag off
there is nothing to give away - an unauthenticated caller can still set the
header, exactly as before.

The narrowing asymmetry is the real security property. A customer-scoped token
that could set the header back to "all" would make the header an authentication
bypass, so the header is rejected outright in that case rather than ignored -
silently ignoring it would let a broken client believe it had switched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import ROLE_CUSTOMER_ADMIN, ROLE_MANUFACTURER_ADMIN
from app.db import get_db
from app.models import Customer, User
from app.security import decode_access_token
from app.services.scoping import Scope

SCOPE_HEADER = "X-Customer-Scope"
ALL_CUSTOMERS = {"", "all", "*", "manufacturer", "null", "none"}

DbSession = Annotated[Session, Depends(get_db)]


def _parse_scope_header(raw: str | None) -> int | None:
    """Turn the header value into a customer id, or None for manufacturer scope."""
    if raw is None or raw.strip().lower() in ALL_CUSTOMERS:
        return None
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{SCOPE_HEADER} must be a numeric customer id or 'all'; "
                f"received {raw!r}."
            ),
        ) from exc


def _require_customer(db: Session, customer_id: int) -> None:
    exists = db.execute(
        select(Customer.customer_id).where(Customer.customer_id == customer_id)
    ).scalars().first()
    if exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No customer with id {customer_id}.",
        )


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if not header:
        return None
    prefix, _, token = header.partition(" ")
    if prefix.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _user_from_token(db: Session, token: str) -> User:
    try:
        claims = decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The access token is not valid.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.execute(
        select(User).where(User.email == str(claims.get("sub", "")))
    ).scalars().first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account is no longer active.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_scope(
    db: DbSession,
    request: Request,
    x_customer_scope: Annotated[
        str | None,
        Header(
            alias=SCOPE_HEADER,
            description=(
                "Customer id to view, or 'all' for the manufacturer view. "
                "Set by the scope switcher in the UI header."
            ),
        ),
    ] = None,
) -> Scope:
    """Resolve the tenant boundary for this request. Every query passes here."""
    requested = _parse_scope_header(x_customer_scope)
    token = _bearer_token(request)

    if token is None:
        if settings.AUTH_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication is required. Send a bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if requested is not None:
            _require_customer(db, requested)
            # The switcher standing in for a customer login: read-write inside
            # that tenant, but rules stay manufacturer-only, exactly as a real
            # customer_admin session would behave.
            return Scope(
                customer_id=requested,
                role=ROLE_CUSTOMER_ADMIN,
                email="fleet@fleetguard.ai",
                full_name="Demo customer administrator",
            )
        return Scope(
            customer_id=None,
            role=ROLE_MANUFACTURER_ADMIN,
            email="admin@fleetguard.ai",
            full_name="Demo manufacturer administrator",
        )

    user = _user_from_token(db, token)

    if user.customer_id is not None:
        # A tenant-bound token cannot be talked out of its tenant.
        #
        # Note the test is on whether the header was *sent*, not on what it
        # parsed to. `X-Customer-Scope: all` parses to None, the same value as
        # no header at all, so checking only `requested is not None` let the
        # one request that matters - a tenant asking for the manufacturer view
        # - through to be quietly narrowed back to its own data. No other
        # customer's rows were ever reachable, but a client that asked to
        # widen and got a 200 has been told it succeeded.
        if x_customer_scope is not None and requested != user.customer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account may only view its own organisation's data.",
            )
        return Scope(
            customer_id=user.customer_id,
            role=user.role,
            user_id=user.user_id,
            email=user.email,
            full_name=user.full_name,
        )

    # Manufacturer token: the header may narrow the view, which is what the
    # scope switcher does for an internal user looking at one account.
    if requested is not None:
        _require_customer(db, requested)
    return Scope(
        customer_id=requested,
        role=user.role,
        user_id=user.user_id,
        email=user.email,
        full_name=user.full_name,
    )


CurrentScope = Annotated[Scope, Depends(get_current_scope)]


def require_write(scope: CurrentScope) -> Scope:
    """Guard for anything that changes state. Viewers are read-only by role."""
    if not scope.can_write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role has read-only access.",
        )
    return scope


def require_rule_author(scope: CurrentScope) -> Scope:
    """Rule authoring is a manufacturer capability (spec section 3)."""
    if not scope.can_manage_rules:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Deploying rules is a manufacturer action. Switch to the "
                "manufacturer view to author rules."
            ),
        )
    return scope


WriteScope = Annotated[Scope, Depends(require_write)]
RuleAuthorScope = Annotated[Scope, Depends(require_rule_author)]


@dataclass(frozen=True)
class Pagination:
    """Shared `limit`/`offset` for every list endpoint (spec section 8)."""

    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(ge=1, le=500, description="Rows to return, 1-500.")] = 50,
    offset: Annotated[int, Query(ge=0, description="Rows to skip.")] = 0,
) -> Pagination:
    """A function rather than a class dependency deliberately.

    This module uses postponed annotation evaluation, and FastAPI cannot
    resolve a nested `Annotated[...]` inside a class `__init__` under it -
    the parameter arrives as an unresolvable forward reference at request
    time. Function dependencies are evaluated against module globals and work
    correctly.
    """
    return Pagination(limit=limit, offset=offset)


PageParams = Annotated[Pagination, Depends(pagination)]
