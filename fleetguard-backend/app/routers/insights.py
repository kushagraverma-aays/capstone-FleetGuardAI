"""Command Centre and Analytics endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.deps import CurrentScope, DbSession
from app.schemas.workflow import (
    CostExposure,
    FailureTrends,
    FleetComparison,
    Overview,
)
from app.services import insights

router = APIRouter(prefix="/api", tags=["insights"])


@router.get(
    "/overview",
    response_model=Overview,
    summary="Command Centre: KPIs, tier mix, trend, top signals and exposure",
)
def get_overview(db: DbSession, scope: CurrentScope) -> Overview:
    return Overview(**insights.overview(db, scope))


@router.get(
    "/analytics/cost-exposure",
    response_model=CostExposure,
    summary="Currency exposure sliced by customer, component, tier or region",
)
def cost_exposure(
    db: DbSession,
    scope: CurrentScope,
    dimension: Annotated[
        str, Query(description="customer | component | tier | region")
    ] = "customer",
) -> CostExposure:
    return CostExposure(**insights.cost_exposure(db, scope, dimension))


@router.get(
    "/analytics/failure-trends",
    response_model=FailureTrends,
    summary="Failures by month and by component, with signal prevalence",
)
def failure_trends(
    db: DbSession,
    scope: CurrentScope,
    months: Annotated[int, Query(ge=1, le=36, description="Months of history.")] = 12,
) -> FailureTrends:
    return FailureTrends(**insights.failure_trends(db, scope, months))


@router.get(
    "/analytics/fleet-comparison",
    response_model=FleetComparison,
    summary="Customers benchmarked against each other and the fleet mean",
)
def fleet_comparison(db: DbSession, scope: CurrentScope) -> FleetComparison:
    return FleetComparison(**insights.fleet_comparison(db, scope))
