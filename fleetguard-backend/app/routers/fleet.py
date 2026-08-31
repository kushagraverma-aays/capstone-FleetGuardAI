"""Customers, vehicles, predictions and RUL.

Handlers here do three things and nothing else: read query parameters, call a
service, and shape the result. Every query goes through `get_current_scope`,
so there is no path from an HTTP request to another tenant's data.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.deps import CurrentScope, DbSession, PageParams
from app.models import Prediction, Rule
from app.schemas.common import Page
from app.schemas.fleet import (
    CustomerOut,
    PredictionDetail,
    PredictionOut,
    RulBands,
    RulDetail,
    RulRow,
    VehicleDetail,
    VehicleOut,
)
from app.services import fleet_queries
from app.services.fleet_queries import PredictionFilters
from app.services.scoring import cross_check_sentence

router = APIRouter(prefix="/api", tags=["fleet"])

# Filters shared by the fleet table, the RUL explorer and the CSV export.
TierFilter = Annotated[
    list[str] | None,
    Query(description="Risk tiers to include: RED, AMBER, GREEN. Repeatable."),
]
CustomerFilter = Annotated[
    list[int] | None, Query(description="Customer ids to include. Repeatable.")
]
RegionFilter = Annotated[list[str] | None, Query(description="Regions. Repeatable.")]
ModelFilter = Annotated[list[str] | None, Query(description="Vehicle models. Repeatable.")]
PartFilter = Annotated[list[str] | None, Query(description="Component codes. Repeatable.")]
SearchFilter = Annotated[
    str | None, Query(description="Free text over VIN, model, region, customer and component.")
]


def _filters(
    tier: list[str] | None,
    customer_id: list[int] | None,
    region: list[str] | None,
    model: list[str] | None,
    part_code: list[str] | None,
    search: str | None,
    max_rul_days: float | None = None,
    escalated_only: bool = False,
) -> PredictionFilters:
    return PredictionFilters(
        tiers=tier,
        customer_ids=customer_id,
        regions=region,
        models=model,
        part_codes=part_code,
        search=search,
        max_rul_days=max_rul_days,
        escalated_only=escalated_only,
    )


# --- customers ---------------------------------------------------------------


@router.get(
    "/customers",
    response_model=list[CustomerOut],
    summary="Fleet operators visible to the caller",
)
def list_customers(db: DbSession, scope: CurrentScope) -> list[CustomerOut]:
    return [CustomerOut(**row) for row in fleet_queries.list_customers(db, scope)]


# --- predictions -------------------------------------------------------------


@router.get(
    "/predictions",
    response_model=Page[PredictionOut],
    summary="Ranked component risk across the fleet",
)
def list_predictions(
    db: DbSession,
    scope: CurrentScope,
    page: PageParams,
    tier: TierFilter = None,
    customer_id: CustomerFilter = None,
    region: RegionFilter = None,
    model: ModelFilter = None,
    part_code: PartFilter = None,
    search: SearchFilter = None,
    max_rul_days: Annotated[
        float | None, Query(description="Only components with at most this many days left.")
    ] = None,
    escalated_only: Annotated[
        bool, Query(description="Only rows escalated to RED by remaining life.")
    ] = False,
    sort: Annotated[
        str, Query(description="probability | rul | vin | cost | health")
    ] = "probability",
    order: Annotated[str, Query(description="asc | desc")] = "desc",
) -> Page[PredictionOut]:
    rows, total = fleet_queries.list_predictions(
        db,
        scope,
        _filters(tier, customer_id, region, model, part_code, search, max_rul_days, escalated_only),
        sort=sort,
        descending=order.lower() != "asc",
        limit=page.limit,
        offset=page.offset,
    )
    return Page.of(
        [PredictionOut(**row) for row in rows], total, page.limit, page.offset
    )


@router.get(
    "/predictions/{vin}/{part_code}",
    response_model=PredictionDetail,
    summary="One component on one vehicle, with drivers, curve and cost",
)
def get_prediction(
    vin: str, part_code: str, db: DbSession, scope: CurrentScope
) -> PredictionDetail:
    row = fleet_queries.get_prediction(db, scope, vin, part_code)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No prediction for {part_code} on {vin} in this view.",
        )

    stored = db.execute(
        select(Prediction).where(
            Prediction.vin == vin, Prediction.part_code == part_code
        )
    ).scalars().first()
    context = fleet_queries.prediction_context(db, vin, part_code)
    part = context["part"]

    active_rule = None
    if stored is not None and stored.rule_id is not None:
        rule = db.get(Rule, stored.rule_id)
        if rule is not None:
            active_rule = fleet_queries.rule_to_dict(db, rule, part.part_name)

    detail = {
        **row,
        "drivers": (stored.drivers or []) if stored else [],
        "trend": (stored.trend or []) if stored else [],
        "curve": (stored.curve or []) if stored else [],
        "cost": fleet_queries.cost_breakdown(db, part, row["failure_probability"]),
        "rule": active_rule,
        "cross_check": cross_check_sentence(
            row["failure_probability"],
            row["risk_tier"],
            row["rul_days"],
            row["rul_km"],
            part.part_name,
        ),
        "km_on_part": context["km_on_part"],
        "design_life_km": part.design_life_km,
        "life_used_pct": context["life_used_pct"],
        "lead_time_days": part.lead_time_days,
    }
    return PredictionDetail(**detail)


# --- vehicles ----------------------------------------------------------------


@router.get(
    "/vehicles",
    response_model=Page[VehicleOut],
    summary="Fleet list with a health summary per vehicle",
)
def list_vehicles(
    db: DbSession,
    scope: CurrentScope,
    page: PageParams,
    tier: TierFilter = None,
    customer_id: CustomerFilter = None,
    region: RegionFilter = None,
    model: ModelFilter = None,
    vehicle_status: Annotated[
        list[str] | None, Query(description="active | workshop | retired. Repeatable.")
    ] = None,
    search: SearchFilter = None,
    sort: Annotated[
        str, Query(description="probability | rul | vin | cost | km | model")
    ] = "probability",
    order: Annotated[str, Query(description="asc | desc")] = "desc",
) -> Page[VehicleOut]:
    rows, total = fleet_queries.list_vehicles(
        db,
        scope,
        customer_ids=customer_id,
        regions=region,
        models=model,
        statuses=vehicle_status,
        tiers=tier,
        search=search,
        sort=sort,
        descending=order.lower() != "asc",
        limit=page.limit,
        offset=page.offset,
    )
    return Page.of([VehicleOut(**row) for row in rows], total, page.limit, page.offset)


@router.get(
    "/vehicles/{vin}",
    response_model=VehicleDetail,
    summary="Vehicle profile: components, service history and telemetry",
)
def get_vehicle(vin: str, db: DbSession, scope: CurrentScope) -> VehicleDetail:
    row = fleet_queries.get_vehicle(db, scope, vin)
    if row is None:
        # Deliberately the same answer as a VIN that does not exist: a customer
        # must not be able to discover another customer's fleet by probing.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No vehicle {vin} in this view.",
        )
    return VehicleDetail(**row)


# --- rul ---------------------------------------------------------------------


@router.get(
    "/rul",
    response_model=Page[RulRow],
    summary="Components ranked by remaining useful life, soonest first",
)
def list_rul(
    db: DbSession,
    scope: CurrentScope,
    page: PageParams,
    band: Annotated[
        str | None,
        Query(description="overdue | within_30_days | within_90_days | healthy"),
    ] = None,
    tier: TierFilter = None,
    customer_id: CustomerFilter = None,
    region: RegionFilter = None,
    model: ModelFilter = None,
    part_code: PartFilter = None,
    search: SearchFilter = None,
) -> Page[RulRow]:
    rows, total = fleet_queries.list_rul(
        db,
        scope,
        _filters(tier, customer_id, region, model, part_code, search),
        band=band,
        limit=page.limit,
        offset=page.offset,
    )
    return Page.of([RulRow(**row) for row in rows], total, page.limit, page.offset)


@router.get(
    "/rul/bands",
    response_model=RulBands,
    summary="How many components sit in each urgency band",
)
def get_rul_bands(
    db: DbSession,
    scope: CurrentScope,
    tier: TierFilter = None,
    customer_id: CustomerFilter = None,
    region: RegionFilter = None,
    model: ModelFilter = None,
    part_code: PartFilter = None,
    search: SearchFilter = None,
) -> RulBands:
    counts = fleet_queries.rul_bands(
        db, scope, _filters(tier, customer_id, region, model, part_code, search)
    )
    return RulBands(**counts)


@router.get(
    "/rul/{vin}/{part_code}",
    response_model=RulDetail,
    summary="The degradation curve and projection for one component",
)
def get_rul(vin: str, part_code: str, db: DbSession, scope: CurrentScope) -> RulDetail:
    row = fleet_queries.get_rul_detail(db, scope, vin, part_code)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No remaining-life estimate for {part_code} on {vin} in this view.",
        )
    return RulDetail(**row)
