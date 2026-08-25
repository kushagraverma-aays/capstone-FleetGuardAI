from __future__ import annotations

import argparse
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import delete, insert

from app.config import SIGNALS
from app.db import SessionLocal
from app.models import JobCard, Part, TelematicsWeekly, Vehicle
from app.services import features

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

PARTS = [
    ("ELC-0152", "Alternator", "Electrical", 120_000),
    ("CLG-0311", "Radiator Fan", "Cooling System", 90_000),
    ("TRN-0207", "Transmission Fluid", "Transmission", 68_000),
    ("BRK-0104", "Brake Pads Front", "Braking", 45_000),
    ("PWT-0455", "Timing Belt", "Powertrain", 150_000),
]

PLANTED_WEIGHTS = {
    "ELC-0152": {
        "coolant_temp_variance": 0.28,
        "overload_duty_share": 0.22,
        "oil_pressure_dips": 0.20,
        "dtc_recurrence_rate": 0.16,
        "battery_voltage_sag": 0.14,
    },
    "CLG-0311": {
        "dtc_recurrence_rate": 0.30,
        "high_rpm_dwell_time": 0.25,
        "short_trip_ratio": 0.25,
        "harsh_braking_frequency": 0.20,
    },
    "TRN-0207": {
        "overload_duty_share": 0.35,
        "high_rpm_dwell_time": 0.30,
        "idle_time_pct": 0.20,
        "coolant_temp_variance": 0.15,
    },
    "BRK-0104": {
        "harsh_braking_frequency": 0.40,
        "overload_duty_share": 0.30,
        "short_trip_ratio": 0.30,
    },
    "PWT-0455": {
        "high_rpm_dwell_time": 0.35,
        "coolant_temp_variance": 0.35,
        "oil_pressure_dips": 0.30,
    },
}

MODELS = [
    ("1015 Light Truck", 90, 140),
    ("1217 Distribution", 110, 170),
    ("2523 Rigid", 130, 200),
    ("2823 Tipper", 80, 130),
    ("4223 Long-Haul Tractor", 250, 380),
]

REGIONS = ["North", "South", "East", "West"]
OPERATORS = ["Sarthi Logistics", "BlueLine Carriers", "Meridian Transport",
             "Rockfort Haulage", "Anand Freight"]

HAZARD_STRESS = 6.0
HAZARD_AGE = 7.9
HAZARD_INTERCEPT = 13.4
RANDOM_FAILURE_SHARE = 0.10
FEEDBACK_START = 0.55
FEEDBACK_STRENGTH = 0.40
PREVENTIVE_MIN = 0.95
PREVENTIVE_MAX = 1.20


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def make_vehicles(n: int, rng: random.Random, today: date) -> list[dict]:
    vehicles = []
    for i in range(n):
        model, lo, hi = rng.choice(MODELS)
        km_per_day = round(rng.uniform(lo, hi), 1)
        age_days = rng.randint(400, 2200)
        vehicles.append(
            {
                "vin": f"MZ4A1{i + 10000:05d}",
                "model": model,
                "region": rng.choice(REGIONS),
                "registration_date": today - timedelta(days=age_days),
                "total_km_driven": 0,
                "avg_km_per_day": km_per_day,
                "fleet_operator": rng.choice(OPERATORS),
            }
        )
    return vehicles


def make_profile(rng: random.Random) -> dict:
    profile = {}
    stressed = set(rng.sample(SIGNALS, rng.randint(0, 3)))
    for sig in SIGNALS:
        base = rng.betavariate(2.2, 5.0)
        if sig in stressed:
            base = clamp(base + rng.uniform(0.10, 0.30))
        profile[sig] = {
            "base": clamp(base, 0.03, 0.85),
            "drift": rng.uniform(0.0000, 0.0035),
            "noise": rng.uniform(0.02, 0.07),
        }
    return profile


def simulate(n_vehicles: int, n_weeks: int, seed: int) -> dict:
    rng = random.Random(seed)
    today = date.today()
    last_monday = today - timedelta(days=today.weekday())
    week_starts = [last_monday - timedelta(weeks=(n_weeks - 1 - w)) for w in range(n_weeks)]

    vehicles = make_vehicles(n_vehicles, rng, today)
    telematics_rows: list[dict] = []
    jobcard_rows: list[dict] = []
    jc_counter = 1

    for veh in vehicles:
        profile = make_profile(rng)
        days_owned = (week_starts[0] - veh["registration_date"]).days
        odometer = max(0.0, days_owned * veh["avg_km_per_day"] * rng.uniform(0.85, 1.0))

        part_km = {}
        preventive_at = {}
        fitment_day = week_starts[0] - timedelta(days=7)
        for code, _, _, life in PARTS:
            part_km[code] = min(odometer, life * rng.uniform(0.05, 0.85))
            preventive_at[code] = rng.uniform(PREVENTIVE_MIN, PREVENTIVE_MAX)
            jobcard_rows.append(
                {
                    "job_card_id": f"JC-{jc_counter:06d}",
                    "vin": veh["vin"],
                    "part_code": code,
                    "failure_date": fitment_day,
                    "odometer_at_failure": int(max(odometer - part_km[code], 0)),
                    "replaced": True,
                    "event_type": "fitment",
                }
            )
            jc_counter += 1

        for w, week_start in enumerate(week_starts):
            active = 0.25 if rng.random() < 0.04 else rng.uniform(0.85, 1.15)
            week_km = veh["avg_km_per_day"] * 7 * active
            odometer += week_km
            for code in part_km:
                part_km[code] += week_km

            raw = {}
            for sig in SIGNALS:
                p = profile[sig]
                value = p["base"] + p["drift"] * w + rng.gauss(0, p["noise"])
                raw[sig] = clamp(value)

            observed = dict(raw)
            for code, _, _, life in PARTS:
                age = part_km[code] / life
                if age > FEEDBACK_START:
                    excess = min(age - FEEDBACK_START, 0.6)
                    for sig, wt in PLANTED_WEIGHTS[code].items():
                        observed[sig] = clamp(observed[sig] + FEEDBACK_STRENGTH * excess * wt * 3)

            row = {
                "vin": veh["vin"],
                "week_start_date": week_start,
                "week_km": round(week_km, 1),
                "odometer_km": round(odometer, 1),
            }
            row.update({s: round(observed[s], 4) for s in SIGNALS})
            telematics_rows.append(row)

            for code, _, _, life in PARTS:
                stress = sum(wt * observed[s] for s, wt in PLANTED_WEIGHTS[code].items())
                age = min(part_km[code] / life, 1.6)
                hazard = sigmoid(HAZARD_STRESS * stress + HAZARD_AGE * age - HAZARD_INTERCEPT)
                if rng.random() < RANDOM_FAILURE_SHARE * 0.002:
                    hazard = 1.0
                failed = rng.random() < hazard
                preventive = (not failed) and age >= preventive_at[code]
                if failed or preventive:
                    event_day = week_start + timedelta(days=rng.randint(0, 6))
                    jobcard_rows.append(
                        {
                            "job_card_id": f"JC-{jc_counter:06d}",
                            "vin": veh["vin"],
                            "part_code": code,
                            "failure_date": event_day,
                            "odometer_at_failure": int(odometer),
                            "replaced": True,
                            "event_type": "failure" if failed else "preventive",
                        }
                    )
                    jc_counter += 1
                    part_km[code] = 0.0

        veh["total_km_driven"] = int(odometer)

    return {"vehicles": vehicles, "telematics": telematics_rows, "jobcards": jobcard_rows}


def write_to_db(payload: dict, truncate: bool) -> None:
    session = SessionLocal()
    try:
        if truncate:
            session.execute(delete(JobCard))
            session.execute(delete(TelematicsWeekly))
            session.execute(delete(Vehicle))
            session.execute(delete(Part))
            session.commit()

        session.execute(
            insert(Part),
            [
                {"part_code": c, "part_name": n, "category": cat, "design_life_km": life}
                for c, n, cat, life in PARTS
            ],
        )
        session.execute(insert(Vehicle), payload["vehicles"])
        session.commit()

        for table, rows in ((TelematicsWeekly, payload["telematics"]), (JobCard, payload["jobcards"])):
            for i in range(0, len(rows), 1000):
                session.execute(insert(table), rows[i : i + 1000])
            session.commit()
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vehicles", type=int, default=400)
    parser.add_argument("--weeks", type=int, default=52)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    print(f"simulating {args.vehicles} vehicles x {args.weeks} weeks x {len(PARTS)} parts ...")
    payload = simulate(args.vehicles, args.weeks, args.seed)

    write_to_db(payload, truncate=not args.keep)
    features.invalidate_cache()

    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "planted_weights.json").write_text(json.dumps(PLANTED_WEIGHTS, indent=2))

    jobs = [j for j in payload["jobcards"] if j["event_type"] == "failure"]
    preventive = len(payload["jobcards"]) - len(jobs)
    by_part: dict[str, int] = {}
    for j in jobs:
        by_part[j["part_code"]] = by_part.get(j["part_code"], 0) + 1

    print(f"[ok] vehicles          {len(payload['vehicles']):>6}")
    print(f"[ok] telematics weeks  {len(payload['telematics']):>6}")
    print(f"[ok] failures          {len(jobs):>6}")
    print(f"[ok] preventive swaps  {preventive:>6}")
    for code, name, _, _ in PARTS:
        print(f"       {name:<20} {by_part.get(code, 0):>4}")
    print("[ok] planted weights written to data/planted_weights.json")
    print("\nNext:  python -m scripts.validate_recovery")


if __name__ == "__main__":
    main()