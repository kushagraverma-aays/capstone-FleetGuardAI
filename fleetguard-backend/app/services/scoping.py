"""Tenant scoping (spec section 3).

`Scope` answers one question: which customer's data may this caller see?
`customer_id is None` means manufacturer scope - the whole fleet across every
customer. Anything else is a single tenant.

This module is deliberately free of FastAPI. The HTTP dependency that builds a
Scope from a header or a JWT lives in `app/deps.py`; the agent tools in the
assistant layer construct the same object. Both then pass it to the very same
query helpers, which is why the API and the assistant cannot disagree about
who is allowed to see what.

The rule for the rest of the codebase is simple and absolute: **a query that
reaches vehicle data without passing through one of the helpers here is a
bug.** Scoping applied at the edge of every handler is scoping that will
eventually be forgotten in one of them.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, select

from app.constants import (
    ROLE_CUSTOMER_ADMIN,
    ROLE_MANUFACTURER_ADMIN,
    ROLE_VIEWER,
)
from app.models import Vehicle


@dataclass(frozen=True)
class Scope:
    """The resolved identity and tenant boundary for one request."""

    customer_id: int | None
    role: str
    user_id: int | None = None
    email: str | None = None
    full_name: str | None = None

    @property
    def is_manufacturer(self) -> bool:
        return self.customer_id is None

    @property
    def can_write(self) -> bool:
        """Viewers may read everything in their tenant and change nothing."""
        return self.role != ROLE_VIEWER

    @property
    def can_manage_rules(self) -> bool:
        """Rule authoring is a manufacturer capability; customers read them."""
        return self.role == ROLE_MANUFACTURER_ADMIN

    @property
    def label(self) -> str:
        if self.is_manufacturer:
            return "All customers (manufacturer view)"
        return f"Customer {self.customer_id}"


MANUFACTURER_SCOPE = Scope(customer_id=None, role=ROLE_MANUFACTURER_ADMIN)


def customer_scope(customer_id: int, role: str = ROLE_CUSTOMER_ADMIN) -> Scope:
    return Scope(customer_id=customer_id, role=role)


def viewer_scope(customer_id: int) -> Scope:
    return Scope(customer_id=customer_id, role=ROLE_VIEWER)


# --- query helpers -----------------------------------------------------------


def limit_vehicles(stmt: Select, scope: Scope) -> Select:
    """Constrain a statement that already selects from or joins vehicle_master."""
    if scope.is_manufacturer:
        return stmt
    return stmt.where(Vehicle.customer_id == scope.customer_id)


def limit_by_customer_column(stmt: Select, scope: Scope, column) -> Select:
    """Constrain a table that carries its own customer_id (notifications, work orders)."""
    if scope.is_manufacturer:
        return stmt
    return stmt.where(column == scope.customer_id)


def vin_subquery(scope: Scope):
    """The VINs this scope may see, as a subquery for `IN` filtering.

    Used where joining vehicle_master would disturb an aggregate - a GROUP BY
    over job cards, for instance.
    """
    stmt = select(Vehicle.vin)
    if not scope.is_manufacturer:
        stmt = stmt.where(Vehicle.customer_id == scope.customer_id)
    return stmt.scalar_subquery()


def owns_vehicle(session, scope: Scope, vin: str) -> bool:
    """Is this VIN inside the caller's tenant?

    Deliberately indistinguishable from "does not exist" at the API layer: a
    customer probing VINs must not be able to learn that another customer's
    truck is real.
    """
    stmt = select(Vehicle.vin).where(Vehicle.vin == vin)
    stmt = limit_vehicles(stmt, scope)
    return session.execute(stmt).scalars().first() is not None


__all__ = [
    "MANUFACTURER_SCOPE",
    "ROLE_CUSTOMER_ADMIN",
    "ROLE_MANUFACTURER_ADMIN",
    "ROLE_VIEWER",
    "Scope",
    "customer_scope",
    "limit_by_customer_column",
    "limit_vehicles",
    "owns_vehicle",
    "viewer_scope",
    "vin_subquery",
]
