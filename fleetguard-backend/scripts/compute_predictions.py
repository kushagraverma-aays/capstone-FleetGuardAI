from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy import delete, insert, select

from app.db import SessionLocal, engine
from app.models import Notification, Part, Prediction
from app.services import engine as scoring
from app.services import features
from app.services.rules_engine import active_rule, preview_rule, rule_weights, save_rule

NOTIFY_MAX_DAYS = 45


def ensure_rules(db, feats) -> dict[str, tuple[int, dict]]:
    out = {}
    parts = db.execute(select(Part)).scalars().all()
    for part in parts:
        rule = active_rule(db, part.part_code)
        if rule is None:
            preview = preview_rule(feats, part.part_code)
            rule = save_rule(db, preview)
            print(f"  built default rule for {part.part_code}: {rule.formula}")
        out[part.part_code] = (rule.rule_id, rule_weights(db, rule))
    return out


def build_rows(feats, parts_meta, rules) -> list[dict]:
    today = date.today()
    rows = []

    for part_code, (rule_id, weights) in rules.items():
        if not weights:
            continue
        part_df = feats[feats["part_code"] == part_code]
        if part_df.empty:
            continue

        scored = scoring.score_frame(part_df, weights).sort_values(["vin", "week_start_date"])
        design_life = float(parts_meta[part_code])

        for vin, history in scored.groupby("vin", sort=False):
            history = history.sort_values("week_start_date")
            last = history.iloc[-1]

            rul = scoring.estimate_rul(history, design_life, float(last["avg_km_per_day"]))
            drivers = scoring.drivers_for_row(last, weights)
            trend = scoring.probability_trend(history)
            probability = float(last["failure_probability"])
            window_from, window_to = scoring.failure_window(rul["rul_days"])

            rows.append(
                {
                    "vin": vin,
                    "part_code": part_code,
                    "rule_id": rule_id,
                    "failure_probability": round(probability, 4),
                    "risk_tier": scoring.risk_tier(probability, rul["rul_days"]),
                    "health_index": rul["health_index"],
                    "window_from_days": window_from,
                    "window_to_days": window_to,
                    "rul_km": rul["rul_km"],
                    "rul_days": rul["rul_days"],
                    "model_confidence": rul["model_confidence"],
                    "degradation_trend": rul["degradation_trend"],
                    "top_signal": drivers[0]["signal"] if drivers else "",
                    "top_signal_share": drivers[0]["share"] if drivers else 0.0,
                    "drivers": drivers,
                    "trend": trend,
                    "curve": rul["curve"],
                    "computed_date": today,
                }
            )
    return rows


def build_notifications(rows, parts_meta_names) -> list[dict]:
    out = []
    for r in rows:
        if r["risk_tier"] != "RED" or r["rul_days"] > NOTIFY_MAX_DAYS:
            continue
        name = parts_meta_names.get(r["part_code"], r["part_code"])
        out.append(
            {
                "vin": r["vin"],
                "part_code": r["part_code"],
                "audience": "vendor",
                "severity": "RED",
                "message": (
                    f"Pre-position {name} for {r['vin']}: failure probability "
                    f"{r['failure_probability']:.0%}, approximately {r['rul_days']} days of "
                    f"useful life remaining."
                ),
                "status": "pending",
            }
        )
        out.append(
            {
                "vin": r["vin"],
                "part_code": r["part_code"],
                "audience": "fleet_owner",
                "severity": "RED",
                "message": (
                    f"{r['vin']} requires a workshop slot within {r['window_from_days']}-"
                    f"{r['window_to_days']} days for {name}."
                ),
                "status": "pending",
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-rules", action="store_true")
    args = parser.parse_args()

    features.invalidate_cache()
    print("building feature table ...")
    feats = features.build_features(engine)
    if feats.empty:
        print("[error] no data. run: python -m scripts.generate_data")
        return

    db = SessionLocal()
    try:
        parts = db.execute(select(Part)).scalars().all()
        parts_meta = {p.part_code: p.design_life_km for p in parts}
        parts_names = {p.part_code: p.part_name for p in parts}

        if args.rebuild_rules:
            from app.models import Rule, RuleSignal

            db.execute(delete(RuleSignal))
            db.execute(delete(Rule))
            db.commit()
            print("[ok] existing rules cleared")

        print("ensuring active rules ...")
        rules = ensure_rules(db, feats)

        print("scoring fleet ...")
        rows = build_rows(feats, parts_meta, rules)

        db.execute(delete(Prediction))
        db.execute(delete(Notification))
        db.commit()

        for i in range(0, len(rows), 500):
            db.execute(insert(Prediction), rows[i : i + 500])
        db.commit()

        notes = build_notifications(rows, parts_names)
        for i in range(0, len(notes), 500):
            db.execute(insert(Notification), notes[i : i + 500])
        db.commit()

        tiers = {"RED": 0, "AMBER": 0, "GREEN": 0}
        for r in rows:
            tiers[r["risk_tier"]] += 1
        urgent = sum(1 for r in rows if r["rul_days"] <= 30)

        print(f"[ok] predictions       {len(rows):>6}")
        print(f"       RED             {tiers['RED']:>6}")
        print(f"       AMBER           {tiers['AMBER']:>6}")
        print(f"       GREEN           {tiers['GREEN']:>6}")
        print(f"[ok] inside 30-day RUL {urgent:>6}")
        print(f"[ok] notifications     {len(notes):>6}")
        print("\nNext:  uvicorn app.main:app --reload")
    finally:
        db.close()


if __name__ == "__main__":
    main()