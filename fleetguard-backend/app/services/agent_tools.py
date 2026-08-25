from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.config import AMBER_THRESHOLD, RED_THRESHOLD, SIGNAL_LABELS, URGENT_RUL_DAYS
from app.config import AMBER_THRESHOLD, RED_THRESHOLD, SIGNAL_LABELS
from app.models import JobCard, Notification, Part, Prediction, Rule, Vehicle
from app.services.rules_engine import active_rule, rule_to_dict


def _resolve_part(db: Session, term: str) -> Part | None:
    if not term:
        return None
    part = db.get(Part, term.upper())
    if part:
        return part
    rows = db.execute(select(Part)).scalars().all()
    needle = term.strip().lower()
    for p in rows:
        if p.part_name.lower() == needle:
            return p
    for p in rows:
        if needle in p.part_name.lower() or needle in p.part_code.lower():
            return p
    return None


def _resolve_vin(db: Session, term: str) -> str | None:
    if not term:
        return None
    veh = db.get(Vehicle, term.upper())
    if veh:
        return veh.vin
    row = db.execute(
        select(Vehicle.vin).where(Vehicle.vin.like(f"%{term.upper()}%"))
    ).scalars().first()
    return row


def part_life_stats(db: Session, part_code: str) -> dict:
    events = db.execute(
        select(JobCard)
        .where(JobCard.part_code == part_code)
        .order_by(JobCard.vin, JobCard.failure_date)
    ).scalars().all()

    by_vin: dict[str, list] = {}
    for e in events:
        by_vin.setdefault(e.vin, []).append(e)

    lives: list[int] = []
    failures = 0
    vins = set()
    for vin, rows in by_vin.items():
        for i, ev in enumerate(rows):
            if ev.event_type != "failure":
                continue
            failures += 1
            vins.add(vin)
            if i > 0:
                km = ev.odometer_at_failure - rows[i - 1].odometer_at_failure
                if km > 0:
                    lives.append(int(km))

    lives.sort()
    median_life = lives[len(lives) // 2] if lives else 0
    return {
        "recorded_failures": failures,
        "affected_vins": len(vins),
        "median_km_on_part_at_failure": median_life,
        "sample_size": len(lives),
    }


def get_fleet_summary(db: Session) -> dict:
    total = db.scalar(select(func.count()).select_from(Prediction)) or 0
    if total == 0:
        return {"error": "no predictions computed yet"}

    tiers = dict(
        db.execute(
            select(Prediction.risk_tier, func.count()).group_by(Prediction.risk_tier)
        ).all()
    )
    urgent = db.scalar(
        select(func.count()).select_from(Prediction).where(Prediction.rul_days <= 30)
    )
    vins = db.scalar(select(func.count(func.distinct(Prediction.vin))))
    computed = db.scalar(select(func.max(Prediction.computed_date)))

    return {
        "vehicles_monitored": vins,
        "component_pairs_scored": total,
        "red_tier": tiers.get("RED", 0),
        "amber_tier": tiers.get("AMBER", 0),
        "green_tier": tiers.get("GREEN", 0),
        "inside_30_day_rul": urgent,
        "red_threshold": RED_THRESHOLD,
        "amber_threshold": AMBER_THRESHOLD,
        "computed_date": str(computed),
        "urgent_rul_days": URGENT_RUL_DAYS,
    }


def list_vehicles_by_risk(db: Session, tier: str = "RED", limit: int = 10) -> dict:
    tier = (tier or "RED").upper()
    rows = db.execute(
        select(Prediction)
        .where(Prediction.risk_tier == tier)
        .order_by(Prediction.failure_probability.desc())
        .limit(min(limit, 25))
    ).scalars().all()
    if not rows:
        return {"tier": tier, "count": 0, "vehicles": []}

    parts = {p.part_code: p.part_name for p in db.execute(select(Part)).scalars().all()}
    total = db.scalar(
        select(func.count()).select_from(Prediction).where(Prediction.risk_tier == tier)
    )
    return {
        "tier": tier,
        "count": total,
        "showing": len(rows),
        "vehicles": [
            {
                "vin": r.vin,
                "part": parts.get(r.part_code, r.part_code),
                "failure_probability": round(r.failure_probability, 3),
                "rul_days": r.rul_days,
            }
            for r in rows
        ],
    }


def get_vehicle_risk(db: Session, vin: str) -> dict:
    resolved = _resolve_vin(db, vin)
    if resolved is None:
        return {"error": f"no vehicle matching '{vin}' in the fleet"}

    veh = db.get(Vehicle, resolved)
    rows = db.execute(
        select(Prediction)
        .where(Prediction.vin == resolved)
        .order_by(Prediction.failure_probability.desc())
    ).scalars().all()
    parts = {p.part_code: p.part_name for p in db.execute(select(Part)).scalars().all()}

    return {
        "vin": resolved,
        "model": veh.model,
        "region": veh.region,
        "fleet_operator": veh.fleet_operator,
        "total_km_driven": veh.total_km_driven,
        "avg_km_per_day": veh.avg_km_per_day,
        "parts": [
            {
                "part_code": r.part_code,
                "part": parts.get(r.part_code, r.part_code),
                "failure_probability": round(r.failure_probability, 3),
                "risk_tier": r.risk_tier,
                "rul_days": r.rul_days,
                "health_index": r.health_index,
            }
            for r in rows
        ],
    }


def explain_prediction(db: Session, vin: str, part: str) -> dict:
    resolved = _resolve_vin(db, vin)
    part_row = _resolve_part(db, part)
    if resolved is None:
        return {"error": f"no vehicle matching '{vin}'"}
    if part_row is None:
        return {"error": f"no part matching '{part}'"}

    pred = db.execute(
        select(Prediction).where(
            Prediction.vin == resolved, Prediction.part_code == part_row.part_code
        )
    ).scalar_one_or_none()
    if pred is None:
        return {"error": f"no prediction for {resolved} / {part_row.part_name}"}

    rule = db.get(Rule, pred.rule_id) if pred.rule_id else None

    return {
        "vin": resolved,
        "part": part_row.part_name,
        "failure_probability": round(pred.failure_probability, 3),
        "risk_tier": pred.risk_tier,
        "escalated_for_short_rul": (
            pred.rul_days <= URGENT_RUL_DAYS
            and pred.failure_probability < RED_THRESHOLD
        ),
        "health_index": pred.health_index,
        "estimated_window_days": [pred.window_from_days, pred.window_to_days],
        "rul_days": pred.rul_days,
        "top_signal": SIGNAL_LABELS.get(pred.top_signal, pred.top_signal),
        "top_signal_share": round(pred.top_signal_share, 3),
        "drivers": [
            {"signal": d["label"], "share": d["share"], "value": d["value"]}
            for d in (pred.drivers or [])
        ],
        "rule_formula": rule.formula if rule else None,
        "rule_precision": rule.precision if rule else None,
        "rule_coverage": rule.coverage if rule else None,
    } 

def get_rul(db: Session, vin: str, part: str) -> dict:
    resolved = _resolve_vin(db, vin)
    part_row = _resolve_part(db, part)
    if resolved is None:
        return {"error": f"no vehicle matching '{vin}'"}
    if part_row is None:
        return {"error": f"no part matching '{part}'"}

    pred = db.execute(
        select(Prediction).where(
            Prediction.vin == resolved, Prediction.part_code == part_row.part_code
        )
    ).scalar_one_or_none()
    if pred is None:
        return {"error": f"no RUL estimate for {resolved} / {part_row.part_name}"}

    veh = db.get(Vehicle, resolved)
    return {
        "vin": resolved,
        "part": part_row.part_name,
        "rul_km": pred.rul_km,
        "rul_days": pred.rul_days,
        "design_life_km": part_row.design_life_km,
        "health_index": pred.health_index,
        "failure_threshold_index": 30,
        "model_confidence_pct": pred.model_confidence,
        "degradation_points_per_month": pred.degradation_trend,
        "observed_km_per_day": veh.avg_km_per_day if veh else None,
        "overdue": pred.rul_days <= 0,
    }


def compare_parts(db: Session, part_a: str, part_b: str) -> dict:
    rows = []
    for term in (part_a, part_b):
        part = _resolve_part(db, term)
        if part is None:
            return {"error": f"no part matching '{term}'"}

        stats = part_life_stats(db, part.part_code)

        avg_prob = db.scalar(
            select(func.avg(Prediction.failure_probability)).where(
                Prediction.part_code == part.part_code
            )
        )
        red = db.scalar(
            select(func.count()).select_from(Prediction).where(
                Prediction.part_code == part.part_code, Prediction.risk_tier == "RED"
            )
        )
        rule = active_rule(db, part.part_code)

        rows.append(
            {
                "part": part.part_name,
                "part_code": part.part_code,
                "design_life_km": part.design_life_km,
                "recorded_failures_12m": stats["recorded_failures"],
                "affected_vins": stats["affected_vins"],
                "median_km_on_part_at_failure": stats["median_km_on_part_at_failure"],
                "life_achieved_vs_design_pct": (
                    round(
                        100 * stats["median_km_on_part_at_failure"] / part.design_life_km, 1
                    )
                    if part.design_life_km
                    else None
                ),
                "mean_failure_probability": round(float(avg_prob or 0), 3),
                "vehicles_in_red_tier": red,
                "top_signal": (
                    SIGNAL_LABELS.get(
                        rule_to_dict(db, rule)["signals"][0]["signal"], ""
                    )
                    if rule and rule_to_dict(db, rule)["signals"]
                    else None
                ),
            }
        )
    return {"comparison": rows}


def get_rule(db: Session, part: str) -> dict:
    part_row = _resolve_part(db, part)
    if part_row is None:
        return {"error": f"no part matching '{part}'"}
    rule = active_rule(db, part_row.part_code)
    if rule is None:
        return {"error": f"no active rule for {part_row.part_name}"}
    return rule_to_dict(db, rule)


def get_notifications(db: Session, vin: str | None = None, limit: int = 10) -> dict:
    stmt = select(Notification).order_by(Notification.id.desc())
    if vin:
        resolved = _resolve_vin(db, vin)
        if resolved is None:
            return {"error": f"no vehicle matching '{vin}'"}
        stmt = stmt.where(Notification.vin == resolved)
    rows = db.execute(stmt.limit(min(limit, 25))).scalars().all()
    return {
        "count": len(rows),
        "notifications": [
            {
                "vin": n.vin,
                "part_code": n.part_code,
                "audience": n.audience,
                "severity": n.severity,
                "message": n.message,
                "status": n.status,
            }
            for n in rows
        ],
    }


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


TOOL_SCHEMAS = [
    _fn(
        "get_fleet_summary",
        "Fleet-wide counts for the current scoring cycle: how many vehicles and "
        "vehicle/component pairs are monitored, how many sit in each risk tier, and how "
        "many are inside the 30-day remaining-useful-life window. Use this for any "
        "'how many' or 'overall' question about the fleet.",
        {},
    ),
    _fn(
        "list_vehicles_by_risk",
        "List the highest-risk vehicles in a given risk tier, ranked by failure "
        "probability. Use for questions like 'which vehicles are red this week'.",
        {
            "tier": {
                "type": "string",
                "enum": ["RED", "AMBER", "GREEN"],
                "description": "Risk tier to list. Defaults to RED.",
            },
            "limit": {"type": "integer", "description": "How many to return, max 25."},
        },
    ),
    _fn(
        "get_vehicle_risk",
        "Every tracked component on one vehicle, with failure probability, risk tier and "
        "days remaining for each. Use when the user names a specific VIN.",
        {"vin": {"type": "string", "description": "Vehicle identification number."}},
        ["vin"],
    ),
    _fn(
        "explain_prediction",
        "Why one component on one vehicle scored the way it did: the contributing "
        "telematics signals and their percentage share of the score, the deployed rule "
        "formula, and that rule's back-tested precision and coverage. Use for any 'why' "
        "question about a specific prediction.",
        {
            "vin": {"type": "string", "description": "Vehicle identification number."},
            "part": {
                "type": "string",
                "description": "Part name or part code, e.g. 'Alternator' or 'ELC-0152'.",
            },
        },
        ["vin", "part"],
    ),
    _fn(
        "get_rul",
        "Remaining useful life for one component on one vehicle, in kilometres and days, "
        "with the health index, model confidence and monthly degradation rate. Use for "
        "'how long until' or 'when should we service' questions.",
        {
            "vin": {"type": "string", "description": "Vehicle identification number."},
            "part": {"type": "string", "description": "Part name or part code."},
        },
        ["vin", "part"],
    ),
    _fn(
        "compare_parts",
        "Compare two components across the fleet on recorded failures, median kilometres "
        "achieved on the part before failure, the percentage of design life that "
        "represents, mean failure probability and red-tier count. Use for durability or "
        "reliability comparisons between parts.",
        {
            "part_a": {"type": "string", "description": "First part name or code."},
            "part_b": {"type": "string", "description": "Second part name or code."},
        },
        ["part_a", "part_b"],
    ),
    _fn(
        "get_rule",
        "The currently deployed failure-probability rule for a component: its formula, "
        "signal weights, and back-tested precision, coverage and lead time.",
        {"part": {"type": "string", "description": "Part name or part code."}},
        ["part"],
    ),
    _fn(
        "get_notifications",
        "Pending alerts raised for red-tier vehicles, addressed either to the parts "
        "vendor or to the fleet owner. Optionally filtered to one VIN.",
        {
            "vin": {"type": "string", "description": "Optional VIN filter."},
            "limit": {"type": "integer", "description": "How many to return, max 25."},
        },
    ),
]


TOOL_NAMES = [t["function"]["name"] for t in TOOL_SCHEMAS]


DISPATCH = {
    "get_fleet_summary": get_fleet_summary,
    "list_vehicles_by_risk": list_vehicles_by_risk,
    "get_vehicle_risk": get_vehicle_risk,
    "explain_prediction": explain_prediction,
    "get_rul": get_rul,
    "compare_parts": compare_parts,
    "get_rule": get_rule,
    "get_notifications": get_notifications,
}


def run_tool(db: Session, name: str, arguments: dict) -> dict:
    fn = DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool '{name}'"}
    try:
        return fn(db, **(arguments or {}))
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    except Exception as exc:
        return {"error": f"{name} failed: {exc}"}