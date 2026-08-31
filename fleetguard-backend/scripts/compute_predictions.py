"""Scoring pipeline: features -> rules -> predictions -> notifications.

Idempotent and re-runnable. Deploys a default rule for any component that does
not have one yet, scores every (vehicle, component) pair from the deployed
rule, and writes one prediction row each.

Run:  python -m scripts.compute_predictions [--redeploy-rules]
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, select

from app.constants import (
    SIGNAL_LABELS,
    TREND_WEEKS,
    WEIGHT_AGE,
    WEIGHT_STRESS,
)
from app.db import SessionLocal
from app.models import JobCard, Notification, Part, Prediction, Vehicle
from app.services import rules_engine
from app.services.cost import estimate_cost_impact
from app.services.features import build_feature_table
from app.services.rul import estimate_rul
from app.services.scoring import assess


def ensure_rules(session, features, failures, redeploy: bool) -> dict[str, dict]:
    """Every component needs a deployed rule before anything can be scored."""
    parts = session.execute(select(Part.part_code, Part.part_name)).all()
    deployed: dict[str, dict] = {}

    for part_code, part_name in parts:
        rule = rules_engine.active_rule(session, part_code)
        if rule is None or redeploy:
            rule = rules_engine.deploy_rule(
                session, features, failures, part_code, created_by="system"
            )
            print(
                f"  deployed {part_name:<20} v{rule.version}  "
                f"precision {rule.precision:.0%}  coverage {rule.coverage:.0%}  "
                f"lead {rule.days_to_alert:.0f}d"
            )
        weights = rules_engine.rule_weights(session, rule)
        deployed[part_code] = {"rule": rule, "weights": weights}

    return deployed


def median_downtime_by_part(session) -> dict[str, float]:
    """Observed downtime for real failures, used for the cost model."""
    rows = session.execute(
        select(JobCard.part_code, func.avg(JobCard.downtime_hours))
        .where(JobCard.event_type == "failure")
        .group_by(JobCard.part_code)
    ).all()
    return {code: float(hours) for code, hours in rows if hours is not None}


def build_drivers(signals: dict[str, float], weights: dict[str, float]) -> list[dict]:
    """Per-signal contribution to this component's stress term."""
    contributions = {
        signal: weight * float(signals.get(signal, 0.0))
        for signal, weight in weights.items()
    }
    total = sum(contributions.values())
    drivers = [
        {
            "signal": signal,
            "label": SIGNAL_LABELS.get(signal, signal),
            "value": round(float(signals.get(signal, 0.0)), 4),
            "weight": round(weights[signal], 4),
            "contribution": round(contribution, 5),
            "share": round(contribution / total * 100, 1) if total else 0.0,
        }
        for signal, contribution in contributions.items()
    ]
    drivers.sort(key=lambda d: d["contribution"], reverse=True)
    return drivers


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the fleet.")
    parser.add_argument(
        "--redeploy-rules",
        action="store_true",
        help="Deploy a fresh rule version for every component before scoring.",
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        print("Building feature table...")
        features = build_feature_table(session)
        if features.empty:
            raise SystemExit("No features. Run 'python -m scripts.manage seed' first.")
        failures = rules_engine.load_failures(session)

        print("Ensuring deployed rules...")
        deployed = ensure_rules(session, features, failures, args.redeploy_rules)

        vehicles = {
            vin: {"avg_km_per_day": km, "customer_id": customer_id}
            for vin, km, customer_id in session.execute(
                select(Vehicle.vin, Vehicle.avg_km_per_day, Vehicle.customer_id)
            ).all()
        }
        parts = {
            code: {
                "name": name,
                "design_life_km": life,
                "unit_cost": float(cost),
                "labour_hours": float(labour),
                "lead_time_days": lead,
            }
            for code, name, life, cost, labour, lead in session.execute(
                select(
                    Part.part_code,
                    Part.part_name,
                    Part.design_life_km,
                    Part.unit_cost,
                    Part.labour_hours,
                    Part.lead_time_days,
                )
            ).all()
        }
        downtime = median_downtime_by_part(session)

        today = date.today()
        prediction_rows: list[dict] = []

        print("Scoring vehicles...")
        for part_code, meta in deployed.items():
            weights = meta["weights"]
            rule = meta["rule"]
            part = parts[part_code]

            frame = features[features["part_code"] == part_code].sort_values(
                ["vin", "week_start_date"]
            )
            if frame.empty or not weights:
                continue

            # Health index for every week, vectorised: the same formula as
            # scoring.assess(), applied to the whole component at once.
            stress = np.zeros(len(frame), dtype=float)
            for signal, weight in weights.items():
                stress = stress + weight * frame[signal].to_numpy(dtype=float)
            age = frame["age_fraction"].to_numpy(dtype=float)
            frame = frame.assign(
                stress=stress,
                health_index=np.clip(
                    100.0 - WEIGHT_AGE * age - WEIGHT_STRESS * stress, 0.0, 100.0
                ),
            )

            for vin, history in frame.groupby("vin", sort=False):
                vehicle = vehicles.get(vin)
                if vehicle is None:
                    continue

                latest = history.iloc[-1]
                rul = estimate_rul(
                    history[["km_on_part", "health_index"]],
                    design_life_km=part["design_life_km"],
                    avg_km_per_day=vehicle["avg_km_per_day"],
                )

                risk = assess(
                    age_fraction=float(latest["age_fraction"]),
                    stress=float(latest["stress"]),
                    rul_days=rul.rul_days,
                )

                signals = {s: float(latest[s]) for s in weights}
                drivers = build_drivers(signals, weights)
                top = drivers[0] if drivers else None

                trend = [
                    {
                        "week": row.week_start_date.date().isoformat(),
                        "probability": round(1.0 - row.health_index / 100.0, 4),
                        "health_index": round(float(row.health_index), 2),
                    }
                    for row in history.tail(TREND_WEEKS).itertuples()
                ]

                cost = estimate_cost_impact(
                    unit_cost=part["unit_cost"],
                    labour_hours=part["labour_hours"],
                    failure_probability=risk.failure_probability,
                    downtime_hours=downtime.get(part_code),
                )

                # A window rather than a single date: confidence widens it.
                spread = max(0.15, 1.0 - rul.model_confidence) * 0.5
                prediction_rows.append(
                    {
                        "vin": vin,
                        "part_code": part_code,
                        "rule_id": rule.rule_id,
                        "failure_probability": risk.failure_probability,
                        "risk_tier": risk.risk_tier,
                        "health_index": risk.health_index,
                        "window_from_days": int(max(0, rul.rul_days * (1 - spread))),
                        "window_to_days": int(rul.rul_days * (1 + spread)),
                        "rul_km": rul.rul_km,
                        "rul_days": rul.rul_days,
                        "model_confidence": rul.model_confidence,
                        "degradation_trend": rul.degradation_trend,
                        "top_signal": top["signal"] if top else None,
                        "top_signal_share": top["share"] if top else 0.0,
                        "escalated": risk.escalated,
                        "escalation_reason": risk.escalation_reason,
                        "drivers": drivers,
                        "trend": trend,
                        "curve": rul.curve,
                        "estimated_cost_impact": cost.estimated_cost_impact,
                        "computed_date": today,
                    }
                )

        print(f"Writing {len(prediction_rows):,} predictions...")
        session.execute(delete(Prediction))
        for start in range(0, len(prediction_rows), 1000):
            session.bulk_insert_mappings(Prediction, prediction_rows[start : start + 1000])
        session.commit()

        notifications = build_notifications(prediction_rows, vehicles, parts)
        print(f"Writing {len(notifications):,} pending notifications...")
        session.execute(delete(Notification).where(Notification.status == "pending"))
        for start in range(0, len(notifications), 1000):
            session.bulk_insert_mappings(Notification, notifications[start : start + 1000])
        session.commit()

        summarise(prediction_rows)
    finally:
        session.close()
    return 0


def build_notifications(
    predictions: list[dict],
    vehicles: dict,
    parts: dict,
) -> list[dict]:
    """One vendor alert and one fleet-owner alert per RED component.

    The two audiences need different things: the vendor needs to move stock
    against a lead time, the operator needs to book a slot and a driver.
    """
    rows: list[dict] = []
    for prediction in predictions:
        if prediction["risk_tier"] != "RED":
            continue
        vin = prediction["vin"]
        part = parts[prediction["part_code"]]
        customer_id = vehicles[vin]["customer_id"]
        rul_days = prediction["rul_days"]
        probability = prediction["failure_probability"]
        severity = "critical" if prediction["escalated"] or rul_days <= 14 else "high"

        rows.append(
            {
                "vin": vin,
                "part_code": prediction["part_code"],
                "customer_id": customer_id,
                "audience": "vendor",
                "severity": severity,
                "title": f"Stock {part['name']} for {vin}",
                "message": (
                    f"{part['name']} on {vin} is at {probability:.0%} failure "
                    f"probability with {rul_days:.0f} days of useful life left. "
                    f"Lead time is {part['lead_time_days']} days, so the part "
                    f"needs to be committed now to arrive before the window closes."
                ),
                "status": "pending",
            }
        )
        rows.append(
            {
                "vin": vin,
                "part_code": prediction["part_code"],
                "customer_id": customer_id,
                "audience": "fleet_owner",
                "severity": severity,
                "title": f"Book {vin} for {part['name']} replacement",
                "message": (
                    f"{vin} is projected to lose its {part['name']} within "
                    f"{rul_days:.0f} days ({probability:.0%} probability). "
                    f"Replacing on plan avoids an estimated "
                    f"{prediction['estimated_cost_impact']:,.0f} in recovery, "
                    f"downtime and premium-parts cost."
                ),
                "status": "pending",
            }
        )
    return rows


def summarise(predictions: list[dict]) -> None:
    frame = pd.DataFrame(predictions)
    if frame.empty:
        print("No predictions written.")
        return

    tiers = frame["risk_tier"].value_counts().to_dict()
    print()
    print("Predictions:")
    for tier in ("RED", "AMBER", "GREEN"):
        print(f"  {tier:<6} {tiers.get(tier, 0):>6}")
    print(f"  escalated by RUL     {int(frame['escalated'].sum()):>6}")
    print(f"  inside 30-day RUL    {int((frame['rul_days'] <= 30).sum()):>6}")
    print(f"  mean confidence      {frame['model_confidence'].mean():>6.2f}")
    print(f"  total cost exposure  {frame['estimated_cost_impact'].sum():>12,.0f}")


if __name__ == "__main__":
    raise SystemExit(main())
