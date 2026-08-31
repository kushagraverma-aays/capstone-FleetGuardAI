"""Shared response shapes.

Every list endpoint in spec section 8 returns the same envelope, so the
frontend can write one table component and one pagination control rather than
one per screen.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiModel(BaseModel):
    """Base for every response model: reads straight off ORM rows."""

    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    """A window onto a longer list, with the full count so the UI can paginate."""

    items: list[T]
    total: int = Field(description="Rows matching the filters, ignoring paging.")
    limit: int
    offset: int

    @classmethod
    def of(cls, items: list[T], total: int, limit: int, offset: int) -> "Page[T]":
        return cls(items=items, total=total, limit=limit, offset=offset)


class ScopeInfo(ApiModel):
    """Who the caller is and what they may see - echoed by /api/auth/me."""

    customer_id: int | None = Field(
        description="Null means the manufacturer view across every customer."
    )
    customer_name: str | None = None
    role: str
    email: str | None = None
    full_name: str | None = None
    is_manufacturer: bool
    can_write: bool
    can_manage_rules: bool
    auth_enabled: bool


class DemoAccount(ApiModel):
    """One seeded sign-in offered on the login screen.

    Served only while `AUTH_ENABLED` is false. The password is included on
    purpose - these are fixtures created by the seed script for a walkthrough,
    and a demo that makes you go and find a password in a script is a demo
    nobody completes. The endpoint disappears entirely the moment enforcement
    is switched on, so the credentials cannot outlive the demo.
    """

    email: str
    password: str
    full_name: str
    role: str
    role_label: str
    description: str
    customer_id: int | None = None
    customer_name: str | None = None


class DemoAccounts(ApiModel):
    accounts: list[DemoAccount]
    note: str


class Acknowledgement(ApiModel):
    """Plain confirmation for actions with nothing useful to return."""

    status: str
    message: str


class LabelledCount(ApiModel):
    label: str
    value: float


class NamedSeries(ApiModel):
    """One line or bar series, ready for Recharts."""

    name: str
    points: list[dict]
