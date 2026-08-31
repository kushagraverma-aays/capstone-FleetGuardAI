"""Read models for the fleet screens (spec section 8).

Everything the API serves for predictions, vehicles, parts and RUL is
assembled here rather than in the route handlers, for two reasons the spec
insists on: business logic must stay callable from a batch job or an Azure
Function, and the assistant's tools in the next phase must return exactly the
same numbers the REST API returns. One implementation, two callers.

Every function takes a `Scope` and applies it. There is no way to ask these
functions for data outside a tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.constants import FAILURE_THRESHOLD_INDEX, SIGNALS
from app.models import (
    Customer,
    JobCard,
    Part,
    Prediction,
    Rule,
    RuleSignal,
    TelematicsWeekly,
    Vehicle,
    WarrantyClaim,
)
from app.services.cost import estimate_cost_impact
from app.services.scoping import Scope, limit_vehicles, vin_subquery

# Urgency bands for the RUL explorer. Overdue is its own band because a flat
# list that opens with hundreds of zeros reads as a broken screen rather than
# an urgent one.
BAND_OVERDUE = "overdue"
BAND_30 = "within_30_days"
BAND_90 = "within_90_days"
BAND_HEALTHY = "healthy"

PREDICTION_SORTS = {
    "probability": Prediction.failure_probability,
    "rul": Prediction.rul_days,
    "vin": Prediction.vin,
    "cost": Prediction.estimated_cost_impact,
    "health": Prediction.health_index,
}

VEHICLE_SORTS = {"vin", "probability", "rul", "cost", "km", "model"}


@dataclass(frozen=True)
class PredictionFilters:
    """The filter set shared by the fleet table, the RUL explorer and export."""

    tiers: list[str] | None = None
    customer_ids: list[int] | None = None
    regions: list[str] | None = None
    models: list[str] | None = None
    part_codes: list[str] | None = None
    search: str | None = None
    max_rul_days: float | None = None
    escalated_only: bool = False


# --- shared statement building ----------------------------------------------


def _prediction_base() -> Select:
    """Predictions joined to everything the fleet table shows."""
    return (
        select(
            Prediction,
            Vehicle.model,
            Vehicle.variant,
            Vehicle.region,
            Vehicle.customer_id,
            Customer.name.label("customer_name"),
            Part.part_name,
            Part.lead_time_days,
        )
        .join(Vehicle, Vehicle.vin == Prediction.vin)
        .join(Customer, Customer.customer_id == Vehicle.customer_id)
        .join(Part, Part.part_code == Prediction.part_code)
    )


def _prediction_conditions(filters: PredictionFilters) -> list:
    conditions = []
    if filters.tiers:
        conditions.append(Prediction.risk_tier.in_([t.upper() for t in filters.tiers]))
    if filters.customer_ids:
        conditions.append(Vehicle.customer_id.in_(filters.customer_ids))
    if filters.regions:
        conditions.append(Vehicle.region.in_(filters.regions))
    if filters.models:
        conditions.append(Vehicle.model.in_(filters.models))
    if filters.part_codes:
        conditions.append(Prediction.part_code.in_(filters.part_codes))
    if filters.max_rul_days is not None:
        conditions.append(Prediction.rul_days <= filters.max_rul_days)
    if filters.escalated_only:
        conditions.append(Prediction.escalated.is_(True))
    if filters.search:
        needle = f"%{filters.search.strip()}%"
        conditions.append(
            or_(
                Prediction.vin.like(needle),
                Vehicle.model.like(needle),
                Vehicle.region.like(needle),
                Customer.name.like(needle),
                Part.part_name.like(needle),
                Prediction.part_code.like(needle),
            )
        )
    return conditions


def _row_to_prediction(row) -> dict:
    prediction: Prediction = row[0]
    return {
        "vin": prediction.vin,
        "part_code": prediction.part_code,
        "part_name": row.part_name,
        "customer_id": row.customer_id,
        "customer_name": row.customer_name,
        "model": row.model,
        "variant": row.variant,
        "region": row.region,
        "failure_probability": prediction.failure_probability,
        "risk_tier": prediction.risk_tier,
        "health_index": prediction.health_index,
        "rul_km": prediction.rul_km,
        "rul_days": prediction.rul_days,
        "window_from_days": prediction.window_from_days,
        "window_to_days": prediction.window_to_days,
        "model_confidence": prediction.model_confidence,
        "degradation_trend": prediction.degradation_trend,
        "top_signal": prediction.top_signal,
        "top_signal_share": prediction.top_signal_share,
        "escalated": prediction.escalated,
        "escalation_reason": prediction.escalation_reason,
        "estimated_cost_impact": float(prediction.estimated_cost_impact),
        "computed_date": prediction.computed_date,
    }


# --- predictions -------------------------------------------------------------


def list_predictions(
    session: Session,
    scope: Scope,
    filters: PredictionFilters,
    sort: str = "probability",
    descending: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    conditions = _prediction_conditions(filters)

    count_stmt = (
        select(func.count())
        .select_from(Prediction)
        .join(Vehicle, Vehicle.vin == Prediction.vin)
        .join(Customer, Customer.customer_id == Vehicle.customer_id)
        .join(Part, Part.part_code == Prediction.part_code)
        .where(*conditions)
    )
    total = session.execute(limit_vehicles(count_stmt, scope)).scalar_one()

    column = PREDICTION_SORTS.get(sort, Prediction.failure_probability)
    ordering = column.desc() if descending else column.asc()

    stmt = limit_vehicles(_prediction_base().where(*conditions), scope)
    # VIN as the tie-breaker keeps paging stable; without it MySQL is free to
    # return the same row on two consecutive pages.
    stmt = stmt.order_by(ordering, Prediction.vin, Prediction.part_code)
    stmt = stmt.limit(limit).offset(offset)

    rows = [_row_to_prediction(row) for row in session.execute(stmt).all()]
    return rows, int(total)


def get_prediction(session: Session, scope: Scope, vin: str, part_code: str) -> dict | None:
    stmt = limit_vehicles(
        _prediction_base().where(
            Prediction.vin == vin, Prediction.part_code == part_code
        ),
        scope,
    )
    row = session.execute(stmt).first()
    return _row_to_prediction(row) if row else None


def prediction_context(session: Session, vin: str, part_code: str) -> dict:
    """The extra facts a detail view needs beyond the stored prediction row."""
    part = session.get(Part, part_code)
    vehicle = session.get(Vehicle, vin)
    km_on_part = current_km_on_part(session, vin, part_code, vehicle)
    return {
        "part": part,
        "vehicle": vehicle,
        "km_on_part": km_on_part,
        "life_used_pct": round(
            100.0 * km_on_part / part.design_life_km, 1
        ) if part and part.design_life_km else 0.0,
    }


def current_km_on_part(
    session: Session,
    vin: str,
    part_code: str,
    vehicle: Vehicle | None = None,
) -> float:
    """Odometer since this component was last installed.

    Every job-card type installs a fresh part - a fitment is the first fit, a
    failure is replaced on the spot, a preventive swap is planned - so the most
    recent event of any type is the part's zero point.
    """
    vehicle = vehicle or session.get(Vehicle, vin)
    if vehicle is None:
        return 0.0
    install_odometer = session.execute(
        select(JobCard.odometer_reading)
        .where(JobCard.vin == vin, JobCard.part_code == part_code)
        .order_by(JobCard.event_date.desc(), JobCard.job_card_id.desc())
        .limit(1)
    ).scalars().first()
    return float(max(0, vehicle.total_km_driven - (install_odometer or 0)))


def cost_breakdown(session: Session, part: Part, failure_probability: float) -> dict:
    """Unplanned versus planned cost for this component (spec 6.8)."""
    observed = session.execute(
        select(func.avg(JobCard.downtime_hours)).where(
            JobCard.part_code == part.part_code, JobCard.event_type == "failure"
        )
    ).scalar_one_or_none()
    impact = estimate_cost_impact(
        unit_cost=float(part.unit_cost),
        labour_hours=float(part.labour_hours),
        failure_probability=failure_probability,
        downtime_hours=float(observed) if observed is not None else None,
    )
    return impact.to_dict()


# --- vehicles ----------------------------------------------------------------


def _vehicle_health_subquery():
    """Per-vehicle roll-up of its component predictions."""
    return (
        select(
            Prediction.vin.label("vin"),
            func.max(Prediction.failure_probability).label("worst_probability"),
            func.min(Prediction.rul_days).label("min_rul_days"),
            func.sum(Prediction.estimated_cost_impact).label("cost_exposure"),
            func.sum(case((Prediction.risk_tier == "RED", 1), else_=0)).label("red_count"),
            func.sum(case((Prediction.risk_tier == "AMBER", 1), else_=0)).label(
                "amber_count"
            ),
        )
        .group_by(Prediction.vin)
        .subquery()
    )


def list_vehicles(
    session: Session,
    scope: Scope,
    *,
    customer_ids: list[int] | None = None,
    regions: list[str] | None = None,
    models: list[str] | None = None,
    statuses: list[str] | None = None,
    tiers: list[str] | None = None,
    search: str | None = None,
    sort: str = "probability",
    descending: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    health = _vehicle_health_subquery()

    conditions = []
    if customer_ids:
        conditions.append(Vehicle.customer_id.in_(customer_ids))
    if regions:
        conditions.append(Vehicle.region.in_(regions))
    if models:
        conditions.append(Vehicle.model.in_(models))
    if statuses:
        conditions.append(Vehicle.status.in_(statuses))
    if search:
        needle = f"%{search.strip()}%"
        conditions.append(
            or_(
                Vehicle.vin.like(needle),
                Vehicle.model.like(needle),
                Vehicle.variant.like(needle),
                Vehicle.region.like(needle),
                Customer.name.like(needle),
            )
        )
    if tiers:
        wanted = {t.upper() for t in tiers}
        tier_conditions = []
        if "RED" in wanted:
            tier_conditions.append(health.c.red_count > 0)
        if "AMBER" in wanted:
            tier_conditions.append(
                and_(health.c.amber_count > 0, health.c.red_count == 0)
            )
        if "GREEN" in wanted:
            tier_conditions.append(
                and_(health.c.red_count == 0, health.c.amber_count == 0)
            )
        if tier_conditions:
            conditions.append(or_(*tier_conditions))

    base = (
        select(
            Vehicle,
            Customer.name.label("customer_name"),
            health.c.worst_probability,
            health.c.min_rul_days,
            health.c.cost_exposure,
            health.c.red_count,
            health.c.amber_count,
        )
        .join(Customer, Customer.customer_id == Vehicle.customer_id)
        .outerjoin(health, health.c.vin == Vehicle.vin)
        .where(*conditions)
    )

    count_stmt = (
        select(func.count())
        .select_from(Vehicle)
        .join(Customer, Customer.customer_id == Vehicle.customer_id)
        .outerjoin(health, health.c.vin == Vehicle.vin)
        .where(*conditions)
    )
    total = session.execute(limit_vehicles(count_stmt, scope)).scalar_one()

    order_map = {
        "vin": Vehicle.vin,
        "probability": health.c.worst_probability,
        "rul": health.c.min_rul_days,
        "cost": health.c.cost_exposure,
        "km": Vehicle.total_km_driven,
        "model": Vehicle.model,
    }
    column = order_map.get(sort, health.c.worst_probability)
    # "Most urgent first" means ascending for RUL and descending for the rest.
    ordering = column.desc() if descending else column.asc()

    stmt = limit_vehicles(base, scope).order_by(ordering, Vehicle.vin)
    stmt = stmt.limit(limit).offset(offset)
    rows = session.execute(stmt).all()

    vins = [row[0].vin for row in rows]
    worst = worst_component_by_vin(session, vins)

    items = []
    for row in rows:
        vehicle: Vehicle = row[0]
        top = worst.get(vehicle.vin)
        red = int(row.red_count or 0)
        amber = int(row.amber_count or 0)
        items.append(
            {
                "vin": vehicle.vin,
                "customer_id": vehicle.customer_id,
                "customer_name": row.customer_name,
                "model": vehicle.model,
                "variant": vehicle.variant,
                "region": vehicle.region,
                "registration_date": vehicle.registration_date,
                "total_km_driven": vehicle.total_km_driven,
                "avg_km_per_day": vehicle.avg_km_per_day,
                "status": vehicle.status,
                "worst_part_code": top["part_code"] if top else None,
                "worst_part_name": top["part_name"] if top else None,
                "worst_probability": round(float(row.worst_probability or 0.0), 6),
                "risk_tier": top["risk_tier"] if top else "GREEN",
                "min_rul_days": float(row.min_rul_days or 0.0),
                "red_count": red,
                "amber_count": amber,
                "cost_exposure": float(row.cost_exposure or 0.0),
            }
        )
    return items, int(total)


def worst_component_by_vin(session: Session, vins: list[str]) -> dict[str, dict]:
    """The single riskiest component per VIN, for the fleet table's summary column."""
    if not vins:
        return {}
    rows = session.execute(
        select(
            Prediction.vin,
            Prediction.part_code,
            Prediction.risk_tier,
            Prediction.failure_probability,
            Part.part_name,
        )
        .join(Part, Part.part_code == Prediction.part_code)
        .where(Prediction.vin.in_(vins))
        .order_by(Prediction.vin, Prediction.failure_probability.desc())
    ).all()

    worst: dict[str, dict] = {}
    for vin, part_code, tier, probability, part_name in rows:
        if vin in worst:
            continue
        worst[vin] = {
            "part_code": part_code,
            "part_name": part_name,
            "risk_tier": tier,
            "failure_probability": probability,
        }
    return worst


def get_vehicle(session: Session, scope: Scope, vin: str) -> dict | None:
    stmt = limit_vehicles(
        select(Vehicle, Customer.name.label("customer_name"))
        .join(Customer, Customer.customer_id == Vehicle.customer_id)
        .where(Vehicle.vin == vin),
        scope,
    )
    row = session.execute(stmt).first()
    if row is None:
        return None

    vehicle: Vehicle = row[0]
    components = vehicle_components(session, vin)
    red = sum(1 for c in components if c["risk_tier"] == "RED")
    amber = sum(1 for c in components if c["risk_tier"] == "AMBER")
    exposure = sum(c["estimated_cost_impact"] for c in components)
    worst = max(components, key=lambda c: c["failure_probability"], default=None)

    return {
        "vin": vehicle.vin,
        "customer_id": vehicle.customer_id,
        "customer_name": row.customer_name,
        "model": vehicle.model,
        "variant": vehicle.variant,
        "region": vehicle.region,
        "registration_date": vehicle.registration_date,
        "total_km_driven": vehicle.total_km_driven,
        "avg_km_per_day": vehicle.avg_km_per_day,
        "status": vehicle.status,
        "worst_part_code": worst["part_code"] if worst else None,
        "worst_part_name": worst["part_name"] if worst else None,
        "worst_probability": worst["failure_probability"] if worst else 0.0,
        "risk_tier": worst["risk_tier"] if worst else "GREEN",
        "min_rul_days": min((c["rul_days"] for c in components), default=0.0),
        "red_count": red,
        "amber_count": amber,
        "cost_exposure": round(exposure, 2),
        "components": components,
        "service_history": vehicle_service_history(session, vin),
        "telemetry": vehicle_telemetry(session, vin),
    }


def vehicle_components(session: Session, vin: str) -> list[dict]:
    rows = session.execute(
        select(Prediction, Part.part_name, Part.category)
        .join(Part, Part.part_code == Prediction.part_code)
        .where(Prediction.vin == vin)
        .order_by(Prediction.failure_probability.desc())
    ).all()
    return [
        {
            "part_code": p.part_code,
            "part_name": part_name,
            "category": category,
            "failure_probability": p.failure_probability,
            "health_index": p.health_index,
            "risk_tier": p.risk_tier,
            "rul_km": p.rul_km,
            "rul_days": p.rul_days,
            "model_confidence": p.model_confidence,
            "escalated": p.escalated,
            "top_signal": p.top_signal,
            "estimated_cost_impact": float(p.estimated_cost_impact),
        }
        for p, part_name, category in rows
    ]


def vehicle_service_history(session: Session, vin: str, limit: int = 200) -> list[dict]:
    rows = session.execute(
        select(JobCard, Part.part_name)
        .join(Part, Part.part_code == JobCard.part_code)
        .where(JobCard.vin == vin)
        .order_by(JobCard.event_date.desc(), JobCard.job_card_id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "job_card_id": job.job_card_id,
            "part_code": job.part_code,
            "part_name": part_name,
            "event_date": job.event_date,
            "event_type": job.event_type,
            "odometer_reading": job.odometer_reading,
            "cost": float(job.cost),
            "downtime_hours": job.downtime_hours,
        }
        for job, part_name in rows
    ]


def vehicle_telemetry(session: Session, vin: str, weeks: int = 52) -> list[dict]:
    rows = session.execute(
        select(TelematicsWeekly)
        .where(TelematicsWeekly.vin == vin)
        .order_by(TelematicsWeekly.week_start_date.desc())
        .limit(weeks)
    ).scalars().all()
    return [
        {
            "week_start_date": row.week_start_date,
            "week_km": row.week_km,
            "odometer_km": row.odometer_km,
            "signals": {signal: round(getattr(row, signal), 4) for signal in SIGNALS},
        }
        for row in reversed(rows)
    ]


# --- parts -------------------------------------------------------------------


def list_parts(session: Session, scope: Scope) -> list[dict]:
    """Component catalogue with the fleet facts the Rule Studio step 1 shows."""
    since = date.today() - timedelta(days=365)
    scoped_vins = vin_subquery(scope)

    failures = dict(
        session.execute(
            select(JobCard.part_code, func.count())
            .where(
                JobCard.event_type == "failure",
                JobCard.event_date >= since,
                JobCard.vin.in_(scoped_vins),
            )
            .group_by(JobCard.part_code)
        ).all()
    )

    tracked_stmt = limit_vehicles(
        select(Prediction.part_code, func.count(), func.sum(
            case((Prediction.risk_tier == "RED", 1), else_=0)
        ))
        .join(Vehicle, Vehicle.vin == Prediction.vin)
        .group_by(Prediction.part_code),
        scope,
    )
    tracked = {
        code: (int(count), int(red or 0))
        for code, count, red in session.execute(tracked_stmt).all()
    }

    active_rules = {
        rule.part_code: rule
        for rule in session.execute(
            select(Rule).where(Rule.is_active.is_(True))
        ).scalars()
    }

    parts = session.execute(select(Part).order_by(Part.category, Part.part_name)).scalars()
    catalogue = []
    for part in parts:
        counted, red = tracked.get(part.part_code, (0, 0))
        rule = active_rules.get(part.part_code)
        catalogue.append(
            {
                "part_code": part.part_code,
                "part_name": part.part_name,
                "category": part.category,
                "design_life_km": part.design_life_km,
                "unit_cost": float(part.unit_cost),
                "lead_time_days": part.lead_time_days,
                "labour_hours": part.labour_hours,
                "tracked_vehicles": counted,
                "failures_12m": int(failures.get(part.part_code, 0)),
                "red_count": red,
                "has_active_rule": rule is not None,
                "rule_precision": rule.precision if rule else None,
                "rule_coverage": rule.coverage if rule else None,
                "rule_days_to_alert": rule.days_to_alert if rule else None,
            }
        )
    return catalogue


def part_history(session: Session, scope: Scope, part_code: str) -> dict | None:
    """Twelve months of events for one component (Rule Studio step 2)."""
    part = session.get(Part, part_code)
    if part is None:
        return None

    scoped_vins = vin_subquery(scope)
    since = date.today() - timedelta(days=365)

    month = func.date_format(JobCard.event_date, "%Y-%m-01")
    monthly_rows = session.execute(
        select(
            month.label("month"),
            func.sum(case((JobCard.event_type == "failure", 1), else_=0)),
            func.sum(case((JobCard.event_type == "preventive", 1), else_=0)),
        )
        .where(
            JobCard.part_code == part_code,
            JobCard.event_date >= since,
            JobCard.vin.in_(scoped_vins),
        )
        .group_by(month)
        .order_by(month)
    ).all()

    events = session.execute(
        select(JobCard.event_type, JobCard.odometer_reading, JobCard.downtime_hours, JobCard.vin)
        .where(JobCard.part_code == part_code, JobCard.vin.in_(scoped_vins))
        .order_by(JobCard.vin, JobCard.event_date)
    ).all()

    # km-on-part at failure needs the previous install for the same vehicle,
    # which is exactly what the ordered walk below reconstructs.
    km_at_failure: list[float] = []
    downtimes: list[float] = []
    previous_odometer: dict[str, int] = {}
    total_failures = 0
    total_preventive = 0
    for event_type, odometer, downtime, vin in events:
        start = previous_odometer.get(vin)
        if event_type == "failure":
            total_failures += 1
            downtimes.append(float(downtime or 0.0))
            if start is not None:
                km_at_failure.append(float(max(0, odometer - start)))
        elif event_type == "preventive":
            total_preventive += 1
        previous_odometer[vin] = odometer

    claims = session.execute(
        select(func.count(), func.coalesce(func.sum(WarrantyClaim.claim_amount), 0))
        .where(
            WarrantyClaim.part_code == part_code,
            WarrantyClaim.vin.in_(scoped_vins),
        )
    ).first()

    median_km = _median(km_at_failure)
    return {
        "part_code": part.part_code,
        "part_name": part.part_name,
        "design_life_km": part.design_life_km,
        "total_failures": total_failures,
        "total_preventive": total_preventive,
        "median_km_at_failure": round(median_km, 1),
        "median_life_used_pct": round(100.0 * median_km / part.design_life_km, 1)
        if part.design_life_km
        else 0.0,
        "mean_downtime_hours": round(sum(downtimes) / len(downtimes), 2) if downtimes else 0.0,
        "warranty_claims": int(claims[0] or 0),
        "warranty_amount": float(claims[1] or 0),
        "monthly": [
            {"month": str(row[0]), "failures": int(row[1] or 0), "preventive": int(row[2] or 0)}
            for row in monthly_rows
        ],
    }


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


# --- rules -------------------------------------------------------------------


def rule_to_dict(session: Session, rule: Rule, part_name: str | None = None) -> dict:
    if part_name is None:
        part = session.get(Part, rule.part_code)
        part_name = part.part_name if part else rule.part_code

    signals = session.execute(
        select(RuleSignal)
        .where(RuleSignal.rule_id == rule.rule_id)
        .order_by(RuleSignal.weight.desc(), RuleSignal.correlation.desc())
    ).scalars().all()

    from app.constants import SIGNAL_LABELS

    return {
        "rule_id": rule.rule_id,
        "part_code": rule.part_code,
        "part_name": part_name,
        "version": rule.version,
        "formula": rule.formula,
        "precision": rule.precision,
        "coverage": rule.coverage,
        "days_to_alert": rule.days_to_alert,
        "sample_failures": rule.sample_failures,
        "is_active": rule.is_active,
        "created_by": rule.created_by,
        "created_at": rule.created_at,
        "signals": [
            {
                "signal": s.signal,
                "label": SIGNAL_LABELS.get(s.signal, s.signal),
                "correlation": s.correlation,
                "weight": s.weight,
                "share": round(s.weight * 100, 1),
                "included": s.included,
            }
            for s in signals
        ],
    }


# --- rul ---------------------------------------------------------------------


def urgency_band(rul_days: float) -> str:
    if rul_days <= 0:
        return BAND_OVERDUE
    if rul_days <= 30:
        return BAND_30
    if rul_days <= 90:
        return BAND_90
    return BAND_HEALTHY


def rul_bands(session: Session, scope: Scope, filters: PredictionFilters) -> dict[str, int]:
    """Counts per urgency band, computed over the whole scope, not the page."""
    conditions = _prediction_conditions(filters)
    stmt = limit_vehicles(
        select(Prediction.rul_days)
        .join(Vehicle, Vehicle.vin == Prediction.vin)
        .join(Customer, Customer.customer_id == Vehicle.customer_id)
        .join(Part, Part.part_code == Prediction.part_code)
        .where(*conditions),
        scope,
    )
    counts = {BAND_OVERDUE: 0, BAND_30: 0, BAND_90: 0, BAND_HEALTHY: 0}
    for (rul_days,) in session.execute(stmt).all():
        counts[urgency_band(float(rul_days))] += 1
    return counts


def list_rul(
    session: Session,
    scope: Scope,
    filters: PredictionFilters,
    band: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Components ranked by urgency: soonest to run out first."""
    conditions = _prediction_conditions(filters)
    if band == BAND_OVERDUE:
        conditions.append(Prediction.rul_days <= 0)
    elif band == BAND_30:
        conditions.append(and_(Prediction.rul_days > 0, Prediction.rul_days <= 30))
    elif band == BAND_90:
        conditions.append(and_(Prediction.rul_days > 30, Prediction.rul_days <= 90))
    elif band == BAND_HEALTHY:
        conditions.append(Prediction.rul_days > 90)

    count_stmt = (
        select(func.count())
        .select_from(Prediction)
        .join(Vehicle, Vehicle.vin == Prediction.vin)
        .join(Customer, Customer.customer_id == Vehicle.customer_id)
        .join(Part, Part.part_code == Prediction.part_code)
        .where(*conditions)
    )
    total = session.execute(limit_vehicles(count_stmt, scope)).scalar_one()

    stmt = limit_vehicles(_prediction_base().where(*conditions), scope)
    stmt = stmt.order_by(Prediction.rul_days.asc(), Prediction.failure_probability.desc())
    stmt = stmt.limit(limit).offset(offset)

    rows = []
    for row in session.execute(stmt).all():
        prediction: Prediction = row[0]
        rows.append(
            {
                "vin": prediction.vin,
                "part_code": prediction.part_code,
                "part_name": row.part_name,
                "customer_id": row.customer_id,
                "customer_name": row.customer_name,
                "model": row.model,
                "rul_days": prediction.rul_days,
                "rul_km": prediction.rul_km,
                "window_from_days": prediction.window_from_days,
                "window_to_days": prediction.window_to_days,
                "failure_probability": prediction.failure_probability,
                "risk_tier": prediction.risk_tier,
                "model_confidence": prediction.model_confidence,
                "degradation_trend": prediction.degradation_trend,
                "urgency_band": urgency_band(float(prediction.rul_days)),
                "lead_time_days": row.lead_time_days,
                "estimated_cost_impact": float(prediction.estimated_cost_impact),
            }
        )
    return rows, int(total)


def get_rul_detail(session: Session, scope: Scope, vin: str, part_code: str) -> dict | None:
    stmt = limit_vehicles(
        select(Prediction, Part, Vehicle)
        .join(Vehicle, Vehicle.vin == Prediction.vin)
        .join(Part, Part.part_code == Prediction.part_code)
        .where(Prediction.vin == vin, Prediction.part_code == part_code),
        scope,
    )
    row = session.execute(stmt).first()
    if row is None:
        return None

    prediction, part, vehicle = row[0], row[1], row[2]
    from app.services.scoring import cross_check_sentence

    return {
        "vin": prediction.vin,
        "part_code": prediction.part_code,
        "part_name": part.part_name,
        "rul_km": prediction.rul_km,
        "rul_days": prediction.rul_days,
        "window_from_days": prediction.window_from_days,
        "window_to_days": prediction.window_to_days,
        "model_confidence": prediction.model_confidence,
        "degradation_trend": prediction.degradation_trend,
        "health_index": prediction.health_index,
        "failure_probability": prediction.failure_probability,
        "risk_tier": prediction.risk_tier,
        "km_on_part": current_km_on_part(session, vin, part_code, vehicle),
        "design_life_km": part.design_life_km,
        "avg_km_per_day": vehicle.avg_km_per_day,
        "failure_threshold_index": FAILURE_THRESHOLD_INDEX,
        "curve": prediction.curve or [],
        "cross_check": cross_check_sentence(
            prediction.failure_probability,
            prediction.risk_tier,
            prediction.rul_days,
            prediction.rul_km,
            part.part_name,
        ),
    }


# --- customers ---------------------------------------------------------------


def list_customers(session: Session, scope: Scope) -> list[dict]:
    stmt = select(Customer).order_by(Customer.name)
    if not scope.is_manufacturer:
        stmt = stmt.where(Customer.customer_id == scope.customer_id)
    customers = session.execute(stmt).scalars().all()

    counts = dict(
        session.execute(
            select(Vehicle.customer_id, func.count()).group_by(Vehicle.customer_id)
        ).all()
    )
    exposure_rows = session.execute(
        select(
            Vehicle.customer_id,
            func.sum(Prediction.estimated_cost_impact),
            func.sum(case((Prediction.risk_tier == "RED", 1), else_=0)),
        )
        .join(Prediction, Prediction.vin == Vehicle.vin)
        .group_by(Vehicle.customer_id)
    ).all()
    exposure = {
        customer_id: (float(cost or 0), int(red or 0))
        for customer_id, cost, red in exposure_rows
    }

    return [
        {
            "customer_id": c.customer_id,
            "name": c.name,
            "region": c.region,
            "contact_email": c.contact_email,
            "contract_tier": c.contract_tier,
            "vehicle_count": int(counts.get(c.customer_id, 0)),
            "red_count": exposure.get(c.customer_id, (0.0, 0))[1],
            "cost_exposure": round(exposure.get(c.customer_id, (0.0, 0))[0], 2),
        }
        for c in customers
    ]
