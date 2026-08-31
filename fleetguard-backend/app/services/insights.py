"""Aggregations behind the Command Centre and the Analytics screen.

These are the numbers a buyer looks at first, so every one of them is derived
from the same prediction rows the detail screens use. Nothing here recomputes
risk with a second formula - if the overview and a vehicle page disagreed, the
product would lose the argument it is trying to win.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.constants import SIGNAL_LABELS, SIGNALS
from app.models import (
    Customer,
    JobCard,
    Notification,
    Part,
    Prediction,
    Rule,
    RuleSignal,
    TelematicsWeekly,
    Vehicle,
)
from app.services.cost import estimate_cost_impact
from app.services.scoping import Scope, limit_by_customer_column, limit_vehicles, vin_subquery

ATTENTION_LIMIT = 12
TREND_MONTHS = 12


def overview(session: Session, scope: Scope) -> dict:
    """Everything the Command Centre renders, in one round trip."""
    totals = session.execute(
        limit_vehicles(
            select(
                func.count(Prediction.id),
                func.count(func.distinct(Prediction.vin)),
                func.count(func.distinct(Prediction.part_code)),
                func.sum(case((Prediction.risk_tier == "RED", 1), else_=0)),
                func.sum(case((Prediction.risk_tier == "AMBER", 1), else_=0)),
                func.sum(case((Prediction.risk_tier == "GREEN", 1), else_=0)),
                func.sum(case((Prediction.escalated.is_(True), 1), else_=0)),
                func.sum(case((Prediction.rul_days <= 30, 1), else_=0)),
                func.sum(Prediction.estimated_cost_impact),
                func.max(Prediction.computed_date),
            ).join(Vehicle, Vehicle.vin == Prediction.vin),
            scope,
        )
    ).first()

    (
        _rows,
        vehicles_monitored,
        components_tracked,
        red,
        amber,
        green,
        escalated,
        inside_30,
        exposure,
        computed_date,
    ) = totals

    open_notifications = session.execute(
        limit_by_customer_column(
            select(func.count())
            .select_from(Notification)
            .where(Notification.status == "pending"),
            scope,
            Notification.customer_id,
        )
    ).scalar_one()

    counted = {"RED": int(red or 0), "AMBER": int(amber or 0), "GREEN": int(green or 0)}
    total_predictions = sum(counted.values()) or 1

    return {
        "scope_label": scope.label,
        "computed_date": computed_date,
        "kpis": {
            "vehicles_monitored": int(vehicles_monitored or 0),
            "components_tracked": int(components_tracked or 0),
            "red_count": counted["RED"],
            "amber_count": counted["AMBER"],
            "green_count": counted["GREEN"],
            "escalated_count": int(escalated or 0),
            "inside_30_day_rul": int(inside_30 or 0),
            "total_cost_exposure": round(float(exposure or 0.0), 2),
            "avoidable_cost": avoidable_cost(session, scope),
            "open_notifications": int(open_notifications or 0),
        },
        "tiers": [
            {
                "tier": tier,
                "count": counted[tier],
                "share": round(counted[tier] / total_predictions, 4),
            }
            for tier in ("RED", "AMBER", "GREEN")
        ],
        "failure_trend": failure_trend(session, scope),
        "top_signals": top_signals(session, scope),
        "needs_attention": needs_attention(session, scope),
        "cost_by_customer": cost_by_customer(session, scope),
    }


def avoidable_cost(session: Session, scope: Scope) -> float:
    """What acting early could save across every RED component in scope.

    The exposure KPI is probability-weighted, which is the honest expected
    value; this is the gross saving on the components already flagged, which is
    the number a fleet manager recognises as a budget line.
    """
    rows = session.execute(
        limit_vehicles(
            select(Prediction.part_code, func.count())
            .join(Vehicle, Vehicle.vin == Prediction.vin)
            .where(Prediction.risk_tier == "RED")
            .group_by(Prediction.part_code),
            scope,
        )
    ).all()
    if not rows:
        return 0.0

    parts = {
        part.part_code: part
        for part in session.execute(select(Part)).scalars()
    }
    downtime = dict(
        session.execute(
            select(JobCard.part_code, func.avg(JobCard.downtime_hours))
            .where(JobCard.event_type == "failure")
            .group_by(JobCard.part_code)
        ).all()
    )

    total = 0.0
    for part_code, count in rows:
        part = parts.get(part_code)
        if part is None:
            continue
        observed = downtime.get(part_code)
        impact = estimate_cost_impact(
            unit_cost=float(part.unit_cost),
            labour_hours=float(part.labour_hours),
            failure_probability=1.0,
            downtime_hours=float(observed) if observed is not None else None,
        )
        total += impact.avoidable_cost * int(count)
    return round(total, 2)


def failure_trend(session: Session, scope: Scope, months: int = TREND_MONTHS) -> list[dict]:
    """Failures and preventive swaps per month over the trailing year."""
    since = date.today() - timedelta(days=months * 31)
    month = func.date_format(JobCard.event_date, "%Y-%m-01")
    rows = session.execute(
        select(
            month.label("month"),
            func.sum(case((JobCard.event_type == "failure", 1), else_=0)),
            func.sum(case((JobCard.event_type == "preventive", 1), else_=0)),
        )
        .where(JobCard.event_date >= since, JobCard.vin.in_(vin_subquery(scope)))
        .group_by(month)
        .order_by(month)
    ).all()
    return [
        {"month": str(row[0]), "failures": int(row[1] or 0), "preventive": int(row[2] or 0)}
        for row in rows
    ]


def top_signals(session: Session, scope: Scope, limit: int = 6) -> list[dict]:
    """The precursor signals carrying the most weight across deployed rules.

    Weight answers "what does the engine rely on"; the fleet mean answers "how
    prevalent is it right now". Showing both stops the chart from being read as
    a severity ranking.
    """
    rows = session.execute(
        select(RuleSignal.signal, func.avg(RuleSignal.weight), func.count())
        .join(Rule, Rule.rule_id == RuleSignal.rule_id)
        .where(Rule.is_active.is_(True), RuleSignal.included.is_(True))
        .group_by(RuleSignal.signal)
        .order_by(func.avg(RuleSignal.weight).desc())
        .limit(limit)
    ).all()
    if not rows:
        return []

    means = fleet_signal_means(session, scope)
    return [
        {
            "signal": signal,
            "label": SIGNAL_LABELS.get(signal, signal),
            "mean_weight": round(float(weight or 0.0), 4),
            "components": int(components or 0),
            "fleet_mean_value": means.get(signal, 0.0),
        }
        for signal, weight, components in rows
    ]


def fleet_signal_means(session: Session, scope: Scope) -> dict[str, float]:
    """Mean of each signal over the most recent four weeks in scope."""
    latest = session.execute(
        select(func.max(TelematicsWeekly.week_start_date))
    ).scalar_one_or_none()
    if latest is None:
        return {}

    since = latest - timedelta(weeks=4)
    row = session.execute(
        select(*[func.avg(getattr(TelematicsWeekly, signal)) for signal in SIGNALS]).where(
            TelematicsWeekly.week_start_date >= since,
            TelematicsWeekly.vin.in_(vin_subquery(scope)),
        )
    ).first()
    if row is None:
        return {}
    return {
        signal: round(float(value), 4)
        for signal, value in zip(SIGNALS, row, strict=True)
        if value is not None
    }


def needs_attention(session: Session, scope: Scope, limit: int = ATTENTION_LIMIT) -> list[dict]:
    """Today's action list: soonest to fail among the RED components.

    Ordered by remaining life rather than probability, because a 95% component
    with 60 days left is a purchase order and a 72% component with 4 days left
    is a phone call this morning.
    """
    rows = session.execute(
        limit_vehicles(
            select(Prediction, Customer.name.label("customer_name"), Part.part_name, Part.lead_time_days)
            .join(Vehicle, Vehicle.vin == Prediction.vin)
            .join(Customer, Customer.customer_id == Vehicle.customer_id)
            .join(Part, Part.part_code == Prediction.part_code)
            .where(Prediction.risk_tier == "RED")
            .order_by(Prediction.rul_days.asc(), Prediction.failure_probability.desc())
            .limit(limit),
            scope,
        )
    ).all()
    attention = []
    for row in rows:
        prediction = row[0]
        attention.append(
            {
                "vin": prediction.vin,
                "part_code": prediction.part_code,
                "part_name": row.part_name,
                "customer_name": row.customer_name,
                "failure_probability": prediction.failure_probability,
                "risk_tier": prediction.risk_tier,
                "rul_days": prediction.rul_days,
                "escalated": prediction.escalated,
                "escalation_reason": prediction.escalation_reason,
                "estimated_cost_impact": float(prediction.estimated_cost_impact),
                "lead_time_days": row.lead_time_days,
            }
        )
    return attention


def cost_by_customer(session: Session, scope: Scope) -> list[dict]:
    rows = session.execute(
        limit_vehicles(
            select(
                Vehicle.customer_id,
                Customer.name,
                func.count(func.distinct(Vehicle.vin)),
                func.sum(Prediction.estimated_cost_impact),
                func.sum(case((Prediction.risk_tier == "RED", 1), else_=0)),
            )
            .join(Customer, Customer.customer_id == Vehicle.customer_id)
            .join(Prediction, Prediction.vin == Vehicle.vin)
            .group_by(Vehicle.customer_id, Customer.name)
            .order_by(func.sum(Prediction.estimated_cost_impact).desc()),
            scope,
        )
    ).all()
    return [
        {
            "customer_id": customer_id,
            "customer_name": name,
            "vehicles": int(vehicles or 0),
            "red_count": int(red or 0),
            "cost_exposure": round(float(cost or 0.0), 2),
            "exposure_per_vehicle": round(float(cost or 0.0) / max(int(vehicles or 1), 1), 2),
        }
        for customer_id, name, vehicles, cost, red in rows
    ]


# --- analytics ---------------------------------------------------------------


COST_DIMENSIONS = {"customer", "component", "tier", "region"}


def cost_exposure(session: Session, scope: Scope, dimension: str = "customer") -> dict:
    """Currency exposure sliced the way the Analytics screen asks for it."""
    if dimension not in COST_DIMENSIONS:
        dimension = "customer"

    key_column = {
        "customer": Customer.name,
        "component": Part.part_name,
        "tier": Prediction.risk_tier,
        "region": Vehicle.region,
    }[dimension]
    id_column = {
        "customer": Vehicle.customer_id,
        "component": Prediction.part_code,
        "tier": Prediction.risk_tier,
        "region": Vehicle.region,
    }[dimension]

    rows = session.execute(
        limit_vehicles(
            select(
                id_column,
                key_column,
                func.sum(Prediction.estimated_cost_impact),
                func.sum(case((Prediction.risk_tier == "RED", 1), else_=0)),
                func.count(),
            )
            .join(Vehicle, Vehicle.vin == Prediction.vin)
            .join(Customer, Customer.customer_id == Vehicle.customer_id)
            .join(Part, Part.part_code == Prediction.part_code)
            .group_by(id_column, key_column)
            .order_by(func.sum(Prediction.estimated_cost_impact).desc()),
            scope,
        )
    ).all()

    # The gross avoidable figure per component is a property of the part, so it
    # is only meaningful on the component slice; elsewhere the exposure column
    # carries the story and avoidable is reported as the same total.
    total_exposure = round(sum(float(row[2] or 0.0) for row in rows), 2)
    total_avoidable = avoidable_cost(session, scope)

    return {
        "dimension": dimension,
        "total_exposure": total_exposure,
        "total_avoidable": total_avoidable,
        "rows": [
            {
                "key": str(key),
                "label": str(label),
                "exposure": round(float(cost or 0.0), 2),
                "avoidable": round(float(cost or 0.0), 2),
                "red_count": int(red or 0),
                "components": int(count or 0),
            }
            for key, label, cost, red, count in rows
        ],
    }


def failure_trends(session: Session, scope: Scope, months: int = TREND_MONTHS) -> dict:
    """Failure counts by month, split by component, plus signal prevalence."""
    since = date.today() - timedelta(days=months * 31)
    month = func.date_format(JobCard.event_date, "%Y-%m-01")

    by_component = session.execute(
        select(month.label("month"), JobCard.part_code, Part.part_name, func.count())
        .join(Part, Part.part_code == JobCard.part_code)
        .where(
            JobCard.event_type == "failure",
            JobCard.event_date >= since,
            JobCard.vin.in_(vin_subquery(scope)),
        )
        .group_by(month, JobCard.part_code, Part.part_name)
        .order_by(month)
    ).all()

    totals = failure_trend(session, scope, months)
    return {
        "months": [row["month"] for row in totals],
        "total_by_month": totals,
        "by_component": [
            {
                "month": str(m),
                "part_code": part_code,
                "part_name": part_name,
                "failures": int(count or 0),
            }
            for m, part_code, part_name, count in by_component
        ],
        "signal_prevalence": top_signals(session, scope, limit=len(SIGNALS)),
    }


def fleet_comparison(session: Session, scope: Scope) -> dict:
    """Customers benchmarked against each other, and against the fleet mean.

    A customer-scoped caller sees only their own row plus the fleet averages -
    enough to know where they stand without seeing a competitor's numbers.
    """
    since = date.today() - timedelta(days=365)

    prediction_rows = session.execute(
        select(
            Vehicle.customer_id,
            func.count(func.distinct(Vehicle.vin)),
            func.avg(Prediction.health_index),
            func.sum(Prediction.estimated_cost_impact),
            func.sum(case((Prediction.risk_tier == "RED", 1), else_=0)),
            func.count(),
        )
        .join(Prediction, Prediction.vin == Vehicle.vin)
        .group_by(Vehicle.customer_id)
    ).all()

    failure_rows = dict(
        session.execute(
            select(Vehicle.customer_id, func.count())
            .join(JobCard, JobCard.vin == Vehicle.vin)
            .where(JobCard.event_type == "failure", JobCard.event_date >= since)
            .group_by(Vehicle.customer_id)
        ).all()
    )

    km_rows = dict(
        session.execute(
            select(Vehicle.customer_id, func.avg(Vehicle.avg_km_per_day)).group_by(
                Vehicle.customer_id
            )
        ).all()
    )

    customers = {
        c.customer_id: c for c in session.execute(select(Customer)).scalars()
    }

    rows = []
    fleet_health_numerator = 0.0
    fleet_predictions = 0
    fleet_vehicles = 0
    fleet_failures = 0

    for customer_id, vehicles, mean_health, exposure, red, predictions in prediction_rows:
        customer = customers.get(customer_id)
        if customer is None:
            continue
        vehicles = int(vehicles or 0)
        predictions = int(predictions or 0)
        failures = int(failure_rows.get(customer_id, 0))

        fleet_health_numerator += float(mean_health or 0.0) * predictions
        fleet_predictions += predictions
        fleet_vehicles += vehicles
        fleet_failures += failures

        if not scope.is_manufacturer and customer_id != scope.customer_id:
            continue

        rows.append(
            {
                "customer_id": customer_id,
                "customer_name": customer.name,
                "region": customer.region,
                "contract_tier": customer.contract_tier,
                "vehicles": vehicles,
                "failures_12m": failures,
                "failures_per_100_vehicles": round(100.0 * failures / vehicles, 1)
                if vehicles
                else 0.0,
                "red_share": round(int(red or 0) / predictions, 4) if predictions else 0.0,
                "mean_health_index": round(float(mean_health or 0.0), 2),
                "cost_exposure": round(float(exposure or 0.0), 2),
                "exposure_per_vehicle": round(float(exposure or 0.0) / vehicles, 2)
                if vehicles
                else 0.0,
                "mean_km_per_day": round(float(km_rows.get(customer_id, 0.0) or 0.0), 1),
            }
        )

    rows.sort(key=lambda r: r["failures_per_100_vehicles"], reverse=True)
    return {
        "fleet_mean_health_index": round(
            fleet_health_numerator / fleet_predictions, 2
        )
        if fleet_predictions
        else 0.0,
        "fleet_failures_per_100_vehicles": round(
            100.0 * fleet_failures / fleet_vehicles, 1
        )
        if fleet_vehicles
        else 0.0,
        "rows": rows,
    }
