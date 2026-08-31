"""Fixtures for the API tests.

These are integration tests: they run against the same MySQL database the
developer seeded with `python -m scripts.manage rebuild`. That is deliberate.
The property under test - that a customer-scoped request cannot reach another
customer's data - is a property of the SQL that actually runs, and a mocked
session would prove nothing about it.

If the database is empty the API tests skip with a message telling you how to
populate it, rather than failing and looking like a regression.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.main import app
from app.models import Customer, Prediction, Vehicle

SEED_HINT = (
    "The API tests need a seeded database. Run: python -m scripts.manage rebuild"
)


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="session")
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def reread(db):
    """Read the database as it stands *now*, not as this session first saw it.

    MySQL defaults to REPEATABLE READ, so a long-lived session keeps the
    snapshot it opened on its first query and will not see rows the API
    committed afterwards. Rolling back ends that transaction and starts a
    fresh snapshot. Without this, a test that asserts "the endpoint wrote an
    audit row" fails against a database that contains exactly that row.
    """

    def _reread():
        db.rollback()
        return db

    return _reread


@pytest.fixture(scope="session")
def seeded(db) -> None:
    predictions = db.execute(select(func.count()).select_from(Prediction)).scalar_one()
    if not predictions:
        pytest.skip(SEED_HINT)


@pytest.fixture(scope="session")
def customer_ids(db, seeded) -> list[int]:
    """Two customers that both own vehicles - the pair every isolation test uses."""
    ids = [
        customer_id
        for (customer_id,) in db.execute(
            select(Vehicle.customer_id)
            .group_by(Vehicle.customer_id)
            .having(func.count() > 0)
            .order_by(Vehicle.customer_id)
        ).all()
    ]
    if len(ids) < 2:
        pytest.skip("Scope isolation needs at least two customers with vehicles.")
    return ids


@pytest.fixture(scope="session")
def customer_a(customer_ids) -> int:
    return customer_ids[0]


@pytest.fixture(scope="session")
def customer_b(customer_ids) -> int:
    return customer_ids[1]


@pytest.fixture(scope="session")
def vehicle_of_b(db, customer_b) -> Vehicle:
    return db.execute(
        select(Vehicle).where(Vehicle.customer_id == customer_b).limit(1)
    ).scalars().first()


@pytest.fixture(scope="session")
def prediction_of_b(db, customer_b) -> Prediction:
    return db.execute(
        select(Prediction)
        .join(Vehicle, Vehicle.vin == Prediction.vin)
        .where(Vehicle.customer_id == customer_b)
        .limit(1)
    ).scalars().first()


@pytest.fixture(scope="session")
def any_prediction(db, seeded) -> Prediction:
    return db.execute(select(Prediction).limit(1)).scalars().first()


@pytest.fixture
def as_customer(customer_a):
    """Headers standing in for the scope switcher set to one customer."""
    return {"X-Customer-Scope": str(customer_a)}


@pytest.fixture(scope="session")
def customer_names(db, seeded) -> dict[int, str]:
    return {c.customer_id: c.name for c in db.execute(select(Customer)).scalars()}
