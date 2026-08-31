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

from app.constants import SIGNAL_LABELS
from app.models import Part, Prediction, Vehicle
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
