"""The Insight Agent's tools (spec section 7).

Every tool here is a thin adapter over the *same* service functions the REST
API calls. Not a copy, not a similar query - the same function. That is the
whole reason the assistant and the dashboard can never quote different
numbers for the same truck, and it is why `Scope` was kept free of FastAPI.

Three rules hold for every tool in this module:

1. **Scope is an argument, never a parameter the model can set.** The loop
   passes the caller's `Scope`; the model cannot see it, name it, or override
   it. A customer-scoped session asking about another customer's VIN gets the
   same "not found" a stranger would.

2. **Absence is reported, never implied.** A tool that finds nothing returns
   `found: false` with a sentence saying so. An empty dict would let the model
   fill the silence with something plausible.

3. **Every number is already rounded and labelled** the way the product
   displays it, so the model is copying a figure rather than doing arithmetic
   on one.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import SIGNAL_LABELS, SIGNALS
from app.models import Customer, Part, Prediction, Vehicle
from app.services import fleet_queries, insights, rules_engine, workflow
from app.services.fleet_queries import PredictionFilters
from app.services.scoping import Scope, limit_vehicles

MAX_ROWS = 25


# --- helpers -----------------------------------------------------------------


def resolve_part(session: Session, value: str | None) -> Part | None:
    """Accept a part code or a component name.

    The model will say "Alternator" far more often than "ELC-0152", and a tool
    that only accepts the code turns every question into a failed round trip.
    """
    if not value:
        return None
    cleaned = value.strip()
    part = session.get(Part, cleaned.upper())
    if part is not None:
        return part
    return session.execute(
        select(Part).where(func.lower(Part.part_name) == cleaned.lower())
    ).scalars().first()


def _not_found(what: str, hint: str = "") -> dict:
    return {"found": False, "message": f"{what} was not found." + (f" {hint}" if hint else "")}


def _vehicle_in_scope(session: Session, scope: Scope, vin: str) -> Vehicle | None:
    return session.execute(
        limit_vehicles(select(Vehicle).where(Vehicle.vin == vin.strip().upper()), scope)
    ).scalars().first()


def resolve_customer(session: Session, scope: Scope, value: str | None) -> Customer | None:
    """Accept a customer name, a partial name, or a numeric id.

    The model is answering questions typed by a person, and a person writes
    "BlueLine" rather than "customer_id 2". A tenant-scoped caller can only
    ever resolve their own organisation, so this cannot be used to discover
    that another customer exists.
    """
    if not value:
        return None
    cleaned = str(value).strip()
    stmt = select(Customer)
    if not scope.is_manufacturer:
        stmt = stmt.where(Customer.customer_id == scope.customer_id)

    if cleaned.isdigit():
        found = session.execute(
            stmt.where(Customer.customer_id == int(cleaned))
        ).scalars().first()
        if found is not None:
            return found

    exact = session.execute(
        stmt.where(func.lower(Customer.name) == cleaned.lower())
    ).scalars().first()
    if exact is not None:
        return exact
    return session.execute(
        stmt.where(Customer.name.ilike(f"%{cleaned}%")).order_by(Customer.name)
    ).scalars().first()


def known_customers_message(session: Session, scope: Scope) -> str:
    stmt = select(Customer.name).order_by(Customer.name)
    if not scope.is_manufacturer:
        stmt = stmt.where(Customer.customer_id == scope.customer_id)
    names = list(session.execute(stmt).scalars())
    return "Customers in this view are: " + ", ".join(names) + "."


def known_components_message(session: Session) -> str:
    names = [p.part_name for p in session.execute(select(Part).order_by(Part.part_name)).scalars()]
    return "Tracked components are: " + ", ".join(names) + "."


# --- the nine tools ----------------------------------------------------------


def get_fleet_summary(session: Session, scope: Scope) -> dict:
    """Counts by tier, vehicles monitored, and how many need action now.

    Tier counts are reported twice on purpose - once per component and once per
    vehicle. Every vehicle carries eight tracked components, so "1,243 red"
    means something very different depending on which is meant, and a single
    ambiguous `red_count` invites the assistant to answer the wrong question
    confidently.
    """
    data = insights.overview(session, scope)
    kpis = data["kpis"]

    red_vehicles = session.execute(
        limit_vehicles(
            select(func.count(func.distinct(Prediction.vin)))
            .select_from(Prediction)
            .join(Vehicle, Vehicle.vin == Prediction.vin)
            .where(Prediction.risk_tier == "RED"),
            scope,
        )
    ).scalar_one()

    return {
        "found": True,
        "scope": data["scope_label"],
        "vehicles_monitored": kpis["vehicles_monitored"],
        "components_tracked_per_vehicle": kpis["components_tracked"],
        "vehicles_with_at_least_one_red_component": int(red_vehicles or 0),
        "red_components": kpis["red_count"],
        "amber_components": kpis["amber_count"],
        "green_components": kpis["green_count"],
        "components_inside_30_day_life": kpis["inside_30_day_rul"],
        "components_escalated_by_remaining_life": kpis["escalated_count"],
        "open_notifications": kpis["open_notifications"],
        "total_cost_exposure": kpis["total_cost_exposure"],
        "avoidable_cost_if_replaced_on_plan": kpis["avoidable_cost"],
        "as_of": str(data["computed_date"]) if data["computed_date"] else None,
    }


def list_vehicles_by_risk(
    session: Session,
    scope: Scope,
    tier: str | None = None,
    part: str | None = None,
    limit: int = 10,
) -> dict:
    """The riskiest vehicles, optionally within one tier or one component."""
    part_row = resolve_part(session, part)
    if part and part_row is None:
        return _not_found(f"Component {part!r}", known_components_message(session))

    filters = PredictionFilters(
        tiers=[tier.upper()] if tier else None,
        part_codes=[part_row.part_code] if part_row else None,
    )
    rows, total = fleet_queries.list_predictions(
        session, scope, filters, sort="probability", descending=True,
        limit=min(max(int(limit), 1), MAX_ROWS), offset=0,
    )
    if not rows:
        return {
            "found": False,
            "message": (
                f"No components match tier={tier or 'any'}, "
                f"component={part or 'any'} in this view."
            ),
            "matching_total": 0,
        }

    return {
        "found": True,
        "matching_total": total,
        "showing": len(rows),
        "vehicles": [
            {
                "vin": r["vin"],
                "customer": r["customer_name"],
                "model": r["model"],
                "component": r["part_name"],
                "risk_tier": r["risk_tier"],
                "failure_probability_pct": round(r["failure_probability"] * 100, 1),
                "rul_days": round(r["rul_days"]),
                "cost_exposure": r["estimated_cost_impact"],
            }
            for r in rows
        ],
    }


def get_vehicle_risk(session: Session, scope: Scope, vin: str) -> dict:
    """Every tracked component on one vehicle."""
    vehicle = _vehicle_in_scope(session, scope, vin)
    if vehicle is None:
        return _not_found(
            f"Vehicle {vin!r}",
            "Either the VIN does not exist or it belongs to another customer.",
        )

    profile = fleet_queries.get_vehicle(session, scope, vehicle.vin)
    return {
        "found": True,
        "vin": vehicle.vin,
        "customer": profile["customer_name"],
        "model": vehicle.model,
        "variant": vehicle.variant,
        "region": vehicle.region,
        "odometer_km": vehicle.total_km_driven,
        "avg_km_per_day": round(vehicle.avg_km_per_day, 1),
        "status": vehicle.status,
        "red_count": profile["red_count"],
        "amber_count": profile["amber_count"],
        "total_cost_exposure": profile["cost_exposure"],
        "components": [
            {
                "component": c["part_name"],
                "part_code": c["part_code"],
                "risk_tier": c["risk_tier"],
                "failure_probability_pct": round(c["failure_probability"] * 100, 1),
                "health_index": round(c["health_index"], 1),
                "rul_days": round(c["rul_days"]),
                "rul_km": round(c["rul_km"]),
                "top_signal": SIGNAL_LABELS.get(c["top_signal"], c["top_signal"]),
                "cost_exposure": c["estimated_cost_impact"],
            }
            for c in profile["components"]
        ],
    }


def explain_prediction(session: Session, scope: Scope, vin: str, part: str) -> dict:
    """Why this component scores what it scores: signals, shares, and the rule."""
    part_row = resolve_part(session, part)
    if part_row is None:
        return _not_found(f"Component {part!r}", known_components_message(session))
    if _vehicle_in_scope(session, scope, vin) is None:
        return _not_found(
            f"Vehicle {vin!r}",
            "Either the VIN does not exist or it belongs to another customer.",
        )

    row = fleet_queries.get_prediction(session, scope, vin.strip().upper(), part_row.part_code)
    if row is None:
        return _not_found(f"A prediction for {part_row.part_name} on {vin!r}")

    stored = session.execute(
        select(Prediction).where(
            Prediction.vin == vin.strip().upper(),
            Prediction.part_code == part_row.part_code,
        )
    ).scalars().first()

    rule = rules_engine.active_rule(session, part_row.part_code)
    rule_summary = None
    if rule is not None:
        rule_summary = {
            "formula": rule.formula,
            "version": rule.version,
            "precision_pct": round(rule.precision * 100, 1),
            "coverage_pct": round(rule.coverage * 100, 1),
            "median_days_of_warning": round(rule.days_to_alert),
            "failures_in_sample": rule.sample_failures,
        }

    return {
        "found": True,
        "vin": row["vin"],
        "component": row["part_name"],
        "risk_tier": row["risk_tier"],
        "failure_probability_pct": round(row["failure_probability"] * 100, 1),
        "health_index": round(row["health_index"], 1),
        "escalated": row["escalated"],
        "escalation_reason": row["escalation_reason"],
        "drivers": [
            {
                "signal": d["label"],
                "share_of_stress_pct": d["share"],
                "current_value": d["value"],
                "weight_in_rule": d["weight"],
            }
            for d in (stored.drivers or [] if stored else [])
        ],
        "rule": rule_summary,
        "cost_exposure": row["estimated_cost_impact"],
    }


def get_rul(session: Session, scope: Scope, vin: str, part: str) -> dict:
    """Remaining useful life in km and days, with the model's confidence."""
    part_row = resolve_part(session, part)
    if part_row is None:
        return _not_found(f"Component {part!r}", known_components_message(session))

    row = fleet_queries.get_rul_detail(
        session, scope, vin.strip().upper(), part_row.part_code
    )
    if row is None:
        return _not_found(
            f"A remaining-life estimate for {part_row.part_name} on {vin!r}",
            "Either the VIN does not exist or it belongs to another customer.",
        )

    return {
        "found": True,
        "vin": row["vin"],
        "component": row["part_name"],
        "rul_days": round(row["rul_days"]),
        "rul_km": round(row["rul_km"]),
        "window_from_days": row["window_from_days"],
        "window_to_days": row["window_to_days"],
        "model_confidence": round(row["model_confidence"], 2),
        "health_points_lost_per_1000km": round(row["degradation_trend"], 2),
        "km_on_part": round(row["km_on_part"]),
        "design_life_km": row["design_life_km"],
        "failure_probability_pct": round(row["failure_probability"] * 100, 1),
        "cross_check": row["cross_check"],
    }


def compare_parts(session: Session, scope: Scope, parts: list[str] | None = None) -> dict:
    """Failure counts, median km on the part at failure, and share of design life."""
    if parts:
        resolved = []
        for name in parts:
            row = resolve_part(session, name)
            if row is None:
                return _not_found(f"Component {name!r}", known_components_message(session))
            resolved.append(row)
    else:
        resolved = list(
            session.execute(select(Part).order_by(Part.part_name)).scalars()
        )

    comparison = []
    for part in resolved:
        history = fleet_queries.part_history(session, scope, part.part_code)
        if history is None:
            continue
        comparison.append(
            {
                "component": part.part_name,
                "part_code": part.part_code,
                "design_life_km": part.design_life_km,
                "failures": history["total_failures"],
                "preventive_replacements": history["total_preventive"],
                "median_km_at_failure": round(history["median_km_at_failure"]),
                "median_share_of_design_life_pct": history["median_life_used_pct"],
                "mean_downtime_hours": history["mean_downtime_hours"],
                "unit_cost": float(part.unit_cost),
                "lead_time_days": part.lead_time_days,
            }
        )

    comparison.sort(key=lambda row: row["failures"], reverse=True)
    return {"found": bool(comparison), "components": comparison}


def get_rule(session: Session, scope: Scope, part: str) -> dict:
    """The deployed formula for a component and how it back-tested."""
    part_row = resolve_part(session, part)
    if part_row is None:
        return _not_found(f"Component {part!r}", known_components_message(session))

    rule = rules_engine.active_rule(session, part_row.part_code)
    if rule is None:
        return _not_found(
            f"A deployed rule for {part_row.part_name}",
            "No rule has been deployed for this component yet.",
        )

    detail = fleet_queries.rule_to_dict(session, rule, part_row.part_name)
    return {
        "found": True,
        "component": part_row.part_name,
        "version": rule.version,
        "formula": rule.formula,
        "signals": [
            {
                "signal": s["label"],
                "weight": s["weight"],
                "share_pct": s["share"],
                "correlation": s["correlation"],
            }
            for s in detail["signals"]
            if s["included"]
        ],
        "precision_pct": round(rule.precision * 100, 1),
        "coverage_pct": round(rule.coverage * 100, 1),
        "median_days_of_warning": round(rule.days_to_alert),
        "failures_in_sample": rule.sample_failures,
        "deployed_on": str(rule.created_at),
    }


def get_notifications(
    session: Session,
    scope: Scope,
    audience: str | None = None,
    severity: str | None = None,
    limit: int = 10,
) -> dict:
    """Outstanding alerts, most severe first."""
    rows, total = workflow.list_notifications(
        session,
        scope,
        audiences=[audience] if audience else None,
        severities=[severity] if severity else None,
        statuses=["pending"],
        limit=min(max(int(limit), 1), MAX_ROWS),
        offset=0,
    )
    if not rows:
        return {
            "found": False,
            "message": "There are no pending alerts in this view.",
            "pending_total": 0,
        }

    return {
        "found": True,
        "pending_total": total,
        "showing": len(rows),
        "alerts": [
            {
                "id": r["id"],
                "vin": r["vin"],
                "component": r["part_name"],
                "customer": r["customer_name"],
                "audience": r["audience"],
                "severity": r["severity"],
                "title": r["title"],
                "message": r["message"],
            }
            for r in rows
        ],
    }


def get_cost_exposure(session: Session, scope: Scope, dimension: str = "customer") -> dict:
    """Currency exposure sliced by customer, component, tier or region."""
    if dimension not in insights.COST_DIMENSIONS:
        return {
            "found": False,
            "message": (
                f"{dimension!r} is not a valid breakdown. Choose one of: "
                + ", ".join(sorted(insights.COST_DIMENSIONS))
                + "."
            ),
        }

    data = insights.cost_exposure(session, scope, dimension)
    return {
        "found": True,
        "dimension": data["dimension"],
        "total_exposure": data["total_exposure"],
        "total_avoidable_if_replaced_on_plan": data["total_avoidable"],
        "breakdown": [
            {
                "name": row["label"],
                "exposure": row["exposure"],
                "red_components": row["red_count"],
                "components_scored": row["components"],
            }
            for row in data["rows"]
        ],
    }


def compare_customers(session: Session, scope: Scope) -> dict:
    """Customers benchmarked against each other and against the fleet mean.

    A customer-scoped caller sees only their own row plus the fleet averages,
    which is enough to know where they stand without seeing a rival's numbers.
    """
    data = insights.fleet_comparison(session, scope)
    if not data["rows"]:
        return {"found": False, "message": "No customer data in this view."}

    return {
        "found": True,
        "fleet_mean_health_index": data["fleet_mean_health_index"],
        "fleet_failures_per_100_vehicles": data["fleet_failures_per_100_vehicles"],
        "customers": [
            {
                "customer": row["customer_name"],
                "region": row["region"],
                "contract_tier": row["contract_tier"],
                "vehicles": row["vehicles"],
                "failures_last_12_months": row["failures_12m"],
                "failures_per_100_vehicles": row["failures_per_100_vehicles"],
                "share_of_components_red_pct": round(row["red_share"] * 100, 1),
                "mean_health_index": row["mean_health_index"],
                "cost_exposure": row["cost_exposure"],
                "exposure_per_vehicle": row["exposure_per_vehicle"],
            }
            for row in data["rows"]
        ],
    }


def find_vehicles(
    session: Session,
    scope: Scope,
    customer: str | None = None,
    model: str | None = None,
    region: str | None = None,
    status: str | None = None,
    tier: str | None = None,
    search: str | None = None,
    limit: int = 10,
) -> dict:
    """Search the vehicle register, and describe the shape of what matched.

    This is the tool for "how many", "which models" and "show me the trucks in
    the North" - questions about the register itself rather than about risk.
    `get_fleet_summary` answers for the whole current view and cannot be
    narrowed, which is what previously made "how many vehicles does customer X
    operate?" come back with the fleet-wide number.

    The composition counts come back alongside the rows because the count is
    usually the answer and the rows are only the evidence.
    """
    customer_row = None
    if customer:
        customer_row = resolve_customer(session, scope, customer)
        if customer_row is None:
            return _not_found(
                f"Customer {customer!r}", known_customers_message(session, scope)
            )

    rows, total = fleet_queries.list_vehicles(
        session,
        scope,
        customer_ids=[customer_row.customer_id] if customer_row else None,
        regions=[region] if region else None,
        models=[model] if model else None,
        statuses=[status] if status else None,
        tiers=[tier.upper()] if tier else None,
        search=search,
        limit=min(max(int(limit), 0), MAX_ROWS),
        offset=0,
    )

    # Composition over the whole match, not over the page: a breakdown built
    # from ten returned rows would describe the ten, and be quoted as if it
    # described the six hundred.
    stmt = limit_vehicles(
        select(Vehicle.model, Vehicle.region, Vehicle.status, func.count()).group_by(
            Vehicle.model, Vehicle.region, Vehicle.status
        ),
        scope,
    )
    if customer_row:
        stmt = stmt.where(Vehicle.customer_id == customer_row.customer_id)
    if model:
        stmt = stmt.where(Vehicle.model == model)
    if region:
        stmt = stmt.where(Vehicle.region == region)
    if status:
        stmt = stmt.where(Vehicle.status == status)

    by_model: dict[str, int] = {}
    by_region: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for model_name, region_name, status_name, count in session.execute(stmt).all():
        by_model[model_name] = by_model.get(model_name, 0) + int(count)
        by_region[region_name] = by_region.get(region_name, 0) + int(count)
        by_status[status_name] = by_status.get(status_name, 0) + int(count)

    if total == 0:
        return {
            "found": False,
            "message": "No vehicles match those filters in this view.",
            "matching_total": 0,
        }

    return {
        "found": True,
        "matching_total": total,
        "customer": customer_row.name if customer_row else None,
        "vehicles_by_model": dict(sorted(by_model.items(), key=lambda kv: -kv[1])),
        "vehicles_by_region": dict(sorted(by_region.items(), key=lambda kv: -kv[1])),
        "vehicles_by_status": by_status,
        "showing": len(rows),
        "vehicles": [
            {
                "vin": r["vin"],
                "customer": r["customer_name"],
                "model": r["model"],
                "variant": r["variant"],
                "region": r["region"],
                "odometer_km": r["total_km_driven"],
                "status": r["status"],
                "risk_tier": r["risk_tier"],
                "worst_component": r["worst_part_name"],
                "min_rul_days": None
                if r["min_rul_days"] is None
                else round(r["min_rul_days"]),
            }
            for r in rows
        ],
    }


def list_customers(session: Session, scope: Scope) -> dict:
    """The customer register: who they are and how large each fleet is."""
    rows = fleet_queries.list_customers(session, scope)
    if not rows:
        return {"found": False, "message": "No customers are visible in this view."}
    return {
        "found": True,
        "customers": [
            {
                "customer": r["name"],
                "region": r["region"],
                "contract_tier": r["contract_tier"],
                "vehicles": r["vehicle_count"],
                "red_components": r["red_count"],
                "cost_exposure": r["cost_exposure"],
            }
            for r in rows
        ],
    }


def get_service_history(session: Session, scope: Scope, vin: str, limit: int = 12) -> dict:
    """The workshop record for one vehicle: what was replaced, when, at what cost."""
    vehicle = _vehicle_in_scope(session, scope, vin)
    if vehicle is None:
        return _not_found(
            f"Vehicle {vin!r}",
            "Either the VIN does not exist or it belongs to another customer.",
        )

    events = fleet_queries.vehicle_service_history(session, vehicle.vin, limit=200)
    if not events:
        return {
            "found": True,
            "vin": vehicle.vin,
            "events_total": 0,
            "message": "This vehicle has no recorded workshop events.",
            "events": [],
        }

    shown = events[: min(max(int(limit), 1), MAX_ROWS)]
    failures = sum(1 for e in events if e["event_type"] == "failure")
    return {
        "found": True,
        "vin": vehicle.vin,
        "events_total": len(events),
        "failures_total": failures,
        "preventive_total": len(events) - failures,
        "last_service_date": str(events[0]["event_date"]),
        "total_spend": round(sum(e["cost"] for e in events), 2),
        "total_downtime_hours": round(sum(e["downtime_hours"] for e in events), 1),
        "showing": len(shown),
        "events": [
            {
                "date": str(e["event_date"]),
                "component": e["part_name"],
                "type": e["event_type"],
                "odometer_km": e["odometer_reading"],
                "cost": e["cost"],
                "downtime_hours": e["downtime_hours"],
            }
            for e in shown
        ],
    }


def get_telemetry_trend(session: Session, scope: Scope, vin: str) -> dict:
    """How one vehicle is being driven, and which signals are getting worse.

    Deliberately a summary rather than the raw weeks. Fifty-two weeks of nine
    signals is several thousand tokens of numbers the model would then have to
    do arithmetic on, and arithmetic is where a grounded assistant stops being
    grounded. The comparison it actually needs - the recent weeks against the
    ones before them - is computed here, and it quotes the result.
    """
    vehicle = _vehicle_in_scope(session, scope, vin)
    if vehicle is None:
        return _not_found(
            f"Vehicle {vin!r}",
            "Either the VIN does not exist or it belongs to another customer.",
        )

    weeks = fleet_queries.vehicle_telemetry(session, vehicle.vin, weeks=8)
    if len(weeks) < 2:
        return {
            "found": False,
            "message": (
                f"There is not enough telematics history for {vehicle.vin} "
                "to show a trend."
            ),
        }

    half = len(weeks) // 2
    earlier, recent = weeks[:half], weeks[half:]

    def mean(rows: list[dict], signal: str) -> float:
        return sum(r["signals"][signal] for r in rows) / len(rows)

    signals = []
    for signal in SIGNALS:
        now, before = mean(recent, signal), mean(earlier, signal)
        change = now - before
        signals.append(
            {
                "signal": SIGNAL_LABELS.get(signal, signal),
                "recent_mean": round(now, 3),
                "previous_mean": round(before, 3),
                "direction": (
                    "rising" if change > 0.02 else "falling" if change < -0.02 else "steady"
                ),
                "change": round(change, 3),
            }
        )
    signals.sort(key=lambda row: row["change"], reverse=True)

    return {
        "found": True,
        "vin": vehicle.vin,
        "weeks_compared": (
            f"most recent {len(recent)} weeks against the {len(earlier)} before them"
        ),
        "period_end": str(weeks[-1]["week_start_date"]),
        "recent_weekly_km": round(sum(r["week_km"] for r in recent) / len(recent)),
        "signal_scale": "0 to 1, where higher is more stressful",
        "signals": signals,
    }


def list_maintenance_due(
    session: Session,
    scope: Scope,
    band: str | None = None,
    part: str | None = None,
    limit: int = 10,
) -> dict:
    """What has to be booked in, soonest first, with the band counts alongside.

    Ordered by remaining life rather than by probability, which is the
    difference between "what is next" and "what is worst" - a scheduling
    question and a triage question are not the same question, and
    `list_vehicles_by_risk` only answers the second one.
    """
    bands = {
        "overdue": fleet_queries.BAND_OVERDUE,
        "within_30_days": fleet_queries.BAND_30,
        "within_90_days": fleet_queries.BAND_90,
        "healthy": fleet_queries.BAND_HEALTHY,
    }
    if band and band not in bands:
        return {
            "found": False,
            "message": f"{band!r} is not a band. Choose one of: " + ", ".join(bands) + ".",
        }

    part_row = resolve_part(session, part)
    if part and part_row is None:
        return _not_found(f"Component {part!r}", known_components_message(session))

    filters = PredictionFilters(part_codes=[part_row.part_code] if part_row else None)
    counts = fleet_queries.rul_bands(session, scope, filters)
    rows, total = fleet_queries.list_rul(
        session,
        scope,
        filters,
        band=bands.get(band) if band else None,
        limit=min(max(int(limit), 1), MAX_ROWS),
        offset=0,
    )

    if not rows:
        return {
            "found": False,
            "message": f"Nothing falls in band={band or 'any'} for this view.",
            "band_counts": counts,
        }

    return {
        "found": True,
        "band_counts": counts,
        "band_meanings": {
            "overdue": "already past its estimated useful life",
            "within_30_days": "1 to 30 days of life left",
            "within_90_days": "31 to 90 days of life left",
            "healthy": "more than 90 days of life left",
        },
        "matching_total": total,
        "showing": len(rows),
        "due": [
            {
                "vin": r["vin"],
                "customer": r["customer_name"],
                "component": r["part_name"],
                "rul_days": round(r["rul_days"]),
                "rul_km": round(r["rul_km"]),
                "risk_tier": r["risk_tier"],
                "part_lead_time_days": r["lead_time_days"],
                "cost_exposure": r["estimated_cost_impact"],
            }
            for r in rows
        ],
    }


def get_failure_trend(session: Session, scope: Scope, months: int = 12) -> dict:
    """Failures and planned replacements per month over the recent past."""
    rows = insights.failure_trend(session, scope, months=min(max(int(months), 1), 24))
    if not rows:
        return {"found": False, "message": "There is no workshop history in this view."}

    return {
        "found": True,
        "months_covered": len(rows),
        "total_failures": sum(r["failures"] for r in rows),
        "total_preventive": sum(r["preventive"] for r in rows),
        "busiest_month": max(rows, key=lambda r: r["failures"])["month"],
        "monthly": rows,
    }


def get_signal_prevalence(session: Session, scope: Scope) -> dict:
    """Which telematics signals the deployed rules lean on, and how high they run.

    Weight is what the engine relies on; the fleet mean is how prevalent the
    signal is right now. They answer different questions and are easy to
    conflate, so both are labelled rather than merged into one ranking.
    """
    rows = insights.top_signals(session, scope, limit=9)
    if not rows:
        return {
            "found": False,
            "message": "No rules are deployed, so no signals are weighted.",
        }
    return {
        "found": True,
        "signal_scale": "0 to 1, where higher is more stressful",
        "signals": [
            {
                "signal": r["label"],
                "mean_weight_across_rules": r["mean_weight"],
                "components_using_it": r["components"],
                "fleet_mean_value": r["fleet_mean_value"],
            }
            for r in rows
        ],
    }


def list_work_orders(
    session: Session,
    scope: Scope,
    status: str | None = None,
    vin: str | None = None,
    limit: int = 10,
) -> dict:
    """Workshop jobs that have been raised: what is booked, and what is still open."""
    # A status this system does not use must be reported, not filtered on. A
    # filter for a value that cannot exist returns nothing, and "nothing
    # matched" reads to the model as "there are none" - so asking for the
    # "open" work orders would have it announce there were none, when what is
    # meant here is "draft".
    if status and status not in workflow.WORK_ORDER_STATUSES:
        return {
            "found": False,
            "message": (
                f"{status!r} is not a work order status. Choose one of: "
                + ", ".join(sorted(workflow.WORK_ORDER_STATUSES))
                + ". A job that has been raised but not yet booked is 'draft'."
            ),
        }

    rows, total = workflow.list_work_orders(
        session,
        scope,
        statuses=[status] if status else None,
        vin=vin.strip().upper() if vin else None,
        limit=min(max(int(limit), 1), MAX_ROWS),
        offset=0,
    )
    if not rows:
        return {
            "found": False,
            "message": (
                f"There are no work orders matching status={status or 'any'} "
                "in this view."
            ),
            "matching_total": 0,
        }
    return {
        "found": True,
        "matching_total": total,
        "showing": len(rows),
        "work_orders": [
            {
                "id": r["id"],
                "vin": r["vin"],
                "component": r["part_name"],
                "customer": r["customer_name"],
                "status": r["status"],
                "scheduled_date": str(r["scheduled_date"]) if r["scheduled_date"] else None,
                "raised_on": str(r["created_at"].date()) if r["created_at"] else None,
                "notes": r["notes"],
            }
            for r in rows
        ],
    }


# --- registry ----------------------------------------------------------------

TOOL_FUNCTIONS: dict[str, Callable[..., dict]] = {
    "get_fleet_summary": get_fleet_summary,
    "list_vehicles_by_risk": list_vehicles_by_risk,
    "get_vehicle_risk": get_vehicle_risk,
    "explain_prediction": explain_prediction,
    "get_rul": get_rul,
    "compare_parts": compare_parts,
    "get_rule": get_rule,
    "get_notifications": get_notifications,
    "get_cost_exposure": get_cost_exposure,
    "compare_customers": compare_customers,
    "find_vehicles": find_vehicles,
    "list_customers": list_customers,
    "get_service_history": get_service_history,
    "get_telemetry_trend": get_telemetry_trend,
    "list_maintenance_due": list_maintenance_due,
    "get_failure_trend": get_failure_trend,
    "get_signal_prevalence": get_signal_prevalence,
    "list_work_orders": list_work_orders,
}

# The schemas the model sees. Descriptions are written for the model, not for a
# developer: they say when to reach for the tool, because a vague description
# is the most common cause of a wrong tool choice.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_fleet_summary",
            "description": (
                "Counts of vehicles and components by risk tier, how many need "
                "action inside 30 days, and total cost exposure. Use this for any "
                "question about the fleet as a whole, or as a first step when the "
                "question is broad."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_vehicles_by_risk",
            "description": (
                "The riskiest vehicle-component pairs, highest failure probability "
                "first. Use for 'which trucks are at risk', 'show me the red ones', "
                "or to find a specific vehicle to talk about."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tier": {
                        "type": "string",
                        "enum": ["RED", "AMBER", "GREEN"],
                        "description": "Restrict to one risk tier.",
                    },
                    "part": {
                        "type": "string",
                        "description": "Component name or code, e.g. 'Alternator'.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many rows to return, 1-25. Default 10.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_vehicle_risk",
            "description": (
                "Every tracked component on one vehicle, with tier, probability and "
                "remaining life. Use whenever the user names a VIN."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "vin": {"type": "string", "description": "The vehicle identification number."}
                },
                "required": ["vin"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_prediction",
            "description": (
                "Why one component on one vehicle scores as it does: the driving "
                "signals with their percentage shares, and the rule that produced "
                "the score with its back-test metrics. Use for 'why', 'what is "
                "driving', or 'explain'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "vin": {"type": "string"},
                    "part": {"type": "string", "description": "Component name or code."},
                },
                "required": ["vin", "part"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rul",
            "description": (
                "Remaining useful life for one component on one vehicle, in "
                "kilometres and days, with model confidence and degradation rate. "
                "Use for 'how long', 'when will it fail', 'how much life is left'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "vin": {"type": "string"},
                    "part": {"type": "string", "description": "Component name or code."},
                },
                "required": ["vin", "part"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_parts",
            "description": (
                "Compare components across the fleet: failure counts, median "
                "kilometres on the part at failure, and what share of design life "
                "that represents. Use for 'which component fails most', or to "
                "compare two named components."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "parts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Component names or codes. Omit for all components.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rule",
            "description": (
                "The deployed scoring formula for a component, its signal weights, "
                "and how it performed in back-testing (precision, coverage, median "
                "days of warning). Use for 'what rule', 'how accurate', 'how does "
                "it decide'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "part": {"type": "string", "description": "Component name or code."}
                },
                "required": ["part"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_notifications",
            "description": (
                "Outstanding alerts awaiting action, most severe first. Use for "
                "'what needs attention', 'any alerts', 'what should I do today'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "audience": {
                        "type": "string",
                        "enum": ["vendor", "fleet_owner"],
                        "description": "vendor alerts are about stocking parts; fleet_owner about booking workshop slots.",
                    },
                    "severity": {"type": "string", "enum": ["critical", "high"]},
                    "limit": {"type": "integer", "description": "1-25. Default 10."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_customers",
            "description": (
                "Compare customers against each other and the fleet average: "
                "failures per 100 vehicles, share of components in the red tier, "
                "mean health index and cost exposure per vehicle. Use for 'which "
                "customer is worst', 'how does X compare', or any failure-rate "
                "question about customers rather than components."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cost_exposure",
            "description": (
                "Cost exposure in currency, broken down by customer, component, "
                "risk tier or region, plus what could be avoided by replacing on "
                "plan. Use for any money question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dimension": {
                        "type": "string",
                        "enum": ["customer", "component", "tier", "region"],
                        "description": "How to slice the exposure. Default customer.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_vehicles",
            "description": (
                "Search the vehicle register and count what matches. Use this for "
                "'how many vehicles does <customer> have', 'which models do they "
                "run', 'list the trucks in <region>', or any question about fleet "
                "size or composition. Returns the total, a breakdown by model, "
                "region and status, and example rows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name, full or partial."},
                    "model": {"type": "string", "description": "Exact vehicle model."},
                    "region": {"type": "string", "description": "Operating region."},
                    "status": {"type": "string", "description": "e.g. active, workshop, retired."},
                    "tier": {
                        "type": "string",
                        "enum": ["RED", "AMBER", "GREEN"],
                        "description": "Worst component tier on the vehicle.",
                    },
                    "search": {"type": "string", "description": "Free text over VIN and model."},
                    "limit": {"type": "integer", "description": "Example rows, 0-25. Default 10."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_customers",
            "description": (
                "The customer register: name, region, contract tier, fleet size and "
                "exposure for each. Use it to answer who the customers are or how "
                "large each fleet is."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_service_history",
            "description": (
                "The workshop record for one vehicle: when it was last serviced, "
                "what was replaced, whether each event was a failure or a planned "
                "swap, the cost and the downtime."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "vin": {"type": "string", "description": "The vehicle identification number."},
                    "limit": {"type": "integer", "description": "Events to list, 1-25. Default 12."},
                },
                "required": ["vin"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_telemetry_trend",
            "description": (
                "How one vehicle is being driven lately and which telematics signals "
                "are rising or falling, comparing the recent weeks with the ones "
                "before them. Use it for 'is it getting worse' and 'why is this truck "
                "under stress'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "vin": {"type": "string", "description": "The vehicle identification number."}
                },
                "required": ["vin"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_maintenance_due",
            "description": (
                "What needs booking in, soonest first, with counts per urgency band. "
                "Use this for scheduling questions - what is overdue, what is due in "
                "the next 30 days, what to order parts for. Ordered by remaining life, "
                "unlike list_vehicles_by_risk which is ordered by probability."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "band": {
                        "type": "string",
                        "enum": ["overdue", "within_30_days", "within_90_days", "healthy"],
                        "description": "Restrict to one urgency band. Omit for all.",
                    },
                    "part": {"type": "string", "description": "Component name or code."},
                    "limit": {"type": "integer", "description": "Rows, 1-25. Default 10."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_failure_trend",
            "description": (
                "Failures and planned replacements per month over the recent past. "
                "Use it for 'are failures going up', 'how many failures last year', "
                "or 'which month was worst'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "months": {"type": "integer", "description": "Months back, 1-24. Default 12."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_signal_prevalence",
            "description": (
                "Which telematics signals the deployed rules weight most heavily, and "
                "how high each runs across the fleet right now. Use it for 'what are "
                "the common precursors' or 'what is driving failures generally'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_work_orders",
            "description": (
                "Workshop jobs that have already been raised, with status, priority "
                "and scheduled date. Alerts are warnings; work orders are the booked "
                "work that followed. Use get_notifications for the former."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": sorted(workflow.WORK_ORDER_STATUSES),
                        "description": (
                            "Restrict to one status. A job raised but not yet "
                            "booked into a workshop is 'draft'."
                        ),
                    },
                    "vin": {"type": "string", "description": "Only this vehicle's work orders."},
                    "limit": {"type": "integer", "description": "Rows, 1-25. Default 10."},
                },
            },
        },
    },
]


def run_tool(session: Session, scope: Scope, name: str, arguments: dict) -> dict:
    """Dispatch one tool call.

    Scope is injected here and is not part of `arguments`, so there is no
    argument the model could supply that would widen what it can see.
    """
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        return {
            "found": False,
            "message": (
                f"There is no tool called {name!r}. Available tools: "
                + ", ".join(sorted(TOOL_FUNCTIONS))
                + "."
            ),
        }

    if "__parse_error__" in arguments:
        return {
            "found": False,
            "message": (
                "The arguments for this call were not valid JSON. Send them again "
                "as a JSON object."
            ),
        }

    try:
        return function(session, scope, **arguments)
    except TypeError as exc:
        # A wrong or missing argument is the model's mistake to correct, not a
        # server error - hand the message back so the next round can fix it.
        return {"found": False, "message": f"Those arguments do not fit {name}: {exc}"}
