"""Synthetic fleet generator with planted cause-and-effect (spec section 5).

The whole product rests on this file. If the telematics signals were random,
the correlation engine would find nothing and every screen downstream would be
empty. So failures are generated *from* the signals using hidden ground-truth
weights, which are written to data/planted_weights.json. The validation script
then checks that the engine rediscovers those weights without ever seeing them.

Run:  python -m scripts.generate_data [--seed N] [--end-date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import math
import random
from datetime import date, timedelta

from sqlalchemy import delete, insert, select

from app.config import DATA_DIR, settings
from app.constants import SIGNALS
from app.db import SessionLocal
from app.models import (
    AuditLog,
    Customer,
    JobCard,
    Notification,
    Part,
    Prediction,
    Rule,
    RuleSignal,
    TelematicsWeekly,
    User,
    Vehicle,
    WarrantyClaim,
    WorkOrder,
)
from app.security import hash_password

# --- fleet composition -------------------------------------------------------

CUSTOMERS = [
    ("Sarthi Logistics", "North", "ops@sarthilogistics.in", "premium", 130),
    ("BlueLine Carriers", "West", "fleet@bluelinecarriers.in", "premium", 120),
    ("Meridian Transport", "South", "maintenance@meridiantransport.in", "basic", 105),
    ("Rockfort Haulage", "East", "control@rockforthaulage.in", "basic", 95),
    ("Anand Freight", "North", "workshop@anandfreight.in", "premium", 85),
    ("Kaveri Roadways", "South", "depot@kaveriroadways.in", "basic", 65),
]

# (model, variant, km/day low, km/day high)
MODELS = [
    ("1015 Light Truck", "Cargo BS6", 90, 145),
    ("1217 Distribution", "Box Body BS6", 110, 175),
    ("2523 Rigid", "Haulage BS6", 130, 205),
    ("2823 Tipper", "Construction BS6", 80, 135),
    ("4223 Long-Haul Tractor", "Sleeper Cab BS6", 250, 385),
]

# (part_code, part_name, category, design_life_km, unit_cost, lead_time_days, labour_hours)
PARTS = [
    ("ELC-0152", "Alternator", "Electrical", 120_000, 18_500, 7, 3.5),
    ("CLG-0311", "Radiator Fan", "Cooling System", 90_000, 9_800, 5, 2.5),
    ("TRN-0207", "Transmission Fluid", "Transmission", 68_000, 6_400, 3, 2.0),
    ("BRK-0104", "Brake Pads Front", "Braking", 45_000, 4_200, 2, 1.5),
    ("PWT-0455", "Timing Belt", "Powertrain", 150_000, 12_600, 10, 6.0),
    ("PWT-0620", "Turbocharger", "Powertrain", 180_000, 46_000, 14, 7.5),
    ("TRN-0388", "Clutch Assembly", "Transmission", 110_000, 31_500, 9, 8.0),
    ("CLG-0145", "Coolant Pump", "Cooling System", 100_000, 7_900, 4, 3.0),
]

# --- the ground truth --------------------------------------------------------
# These weights are what the correlation engine must rediscover. They are never
# read by the engine, the API, or the UI - only by the validation script.

PLANTED_WEIGHTS: dict[str, dict[str, float]] = {
    "ELC-0152": {  # Alternator
        "coolant_temp_variance": 0.26,
        "overload_duty_share": 0.23,
        "battery_voltage_sag": 0.20,
        "oil_pressure_dips": 0.17,
        "dtc_recurrence_rate": 0.14,
    },
    "CLG-0311": {  # Radiator Fan
        "dtc_recurrence_rate": 0.31,
        "high_rpm_dwell_time": 0.26,
        "short_trip_ratio": 0.23,
        "harsh_braking_frequency": 0.20,
    },
    "TRN-0207": {  # Transmission Fluid
        "overload_duty_share": 0.34,
        "high_rpm_dwell_time": 0.28,
        "idle_time_pct": 0.22,
        "coolant_temp_variance": 0.16,
    },
    "BRK-0104": {  # Brake Pads Front
        "harsh_braking_frequency": 0.42,
        "overload_duty_share": 0.31,
        "short_trip_ratio": 0.27,
    },
    "PWT-0455": {  # Timing Belt
        "high_rpm_dwell_time": 0.38,
        "coolant_temp_variance": 0.34,
        "oil_pressure_dips": 0.28,
    },
    "PWT-0620": {  # Turbocharger
        "high_rpm_dwell_time": 0.40,
        "oil_pressure_dips": 0.33,
        "overload_duty_share": 0.27,
    },
    "TRN-0388": {  # Clutch Assembly
        "short_trip_ratio": 0.39,
        "overload_duty_share": 0.32,
        "harsh_braking_frequency": 0.29,
    },
    "CLG-0145": {  # Coolant Pump
        "coolant_temp_variance": 0.41,
        "dtc_recurrence_rate": 0.31,
        "idle_time_pct": 0.28,
    },
}

# --- simulation parameters ---------------------------------------------------

N_VEHICLES = 600
N_WEEKS = 52

# hazard = sigmoid(HAZARD_STRESS*stress + HAZARD_AGE*age - HAZARD_INTERCEPT)
#
# The spec suggested 6.0 / 7.9 / 13.4. Two changes were needed:
#   * the intercept had to rise a long way - 13.4 produced 2,945 failures
#     against a target band of 1,000-1,500;
#   * the stress coefficient was raised from 6.0 to 14.0 so the signals
#     genuinely discriminate. At 6.0 age swamped stress near end of life and
#     signal recovery sat at 96.4%; at 14.0 it is 100% and back-test
#     precision improves too. Age still dominates near end of life, which the
#     generator verifies and prints on every run.
HAZARD_STRESS = 14.0
HAZARD_AGE = 7.9
HAZARD_INTERCEPT = 19.9

# A flat, signal-independent hazard producing roughly 10% of all failures.
# A model that hits perfect precision is a red flag, not a selling point.
NOISE_HAZARD = 0.0006

# Once a part passes this share of design life it starts pushing up its own
# precursor signals - a dying alternator really does cause voltage sag. This is
# what makes the degradation curves slope realistically.
FEEDBACK_START = 0.55
FEEDBACK_STRENGTH = 0.40

# Preventive replacement threshold, as a multiple of design life. Without this
# parts sail past design life, age saturates and discrimination collapses.
PREVENTIVE_MIN = 0.95
PREVENTIVE_MAX = 1.20

# Warranty cover and the share of in-warranty failures that get claimed.
WARRANTY_YEARS = 2
WARRANTY_KM = 200_000
WARRANTY_CLAIM_RATE = 0.62

# Configuration, not a constant, so the seeded hash and the password the login
# screen offers can never drift apart. See Settings.DEMO_PASSWORD.
DEMO_PASSWORD = settings.DEMO_PASSWORD


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def most_recent_monday(anchor: date) -> date:
    return anchor - timedelta(days=anchor.weekday())


def build_signal_profile(rng: random.Random) -> dict[str, dict[str, float]]:
    """A per-vehicle personality.

    Only a random subset of 0-3 signals is elevated. Elevating every signal
    together would make them all move as one and manufacture cross-correlation
    that the engine would then faithfully - and wrongly - report.
    """
    elevated = set(rng.sample(SIGNALS, rng.randint(0, 3)))
    profile: dict[str, dict[str, float]] = {}
    for signal in SIGNALS:
        base = rng.betavariate(2.2, 5.0)
        if signal in elevated:
            base = clamp(base + rng.uniform(0.12, 0.32))
        profile[signal] = {
            "base": clamp(base, 0.03, 0.85),
            "drift": rng.uniform(0.0, 0.0035),
            "noise": rng.uniform(0.02, 0.07),
        }
    return profile


def make_customers() -> list[dict]:
    return [
        {
            "customer_id": idx + 1,
            "name": name,
            "region": region,
            "contact_email": email,
            "contract_tier": tier,
        }
        for idx, (name, region, email, tier, _share) in enumerate(CUSTOMERS)
    ]


def make_users(customers: list[dict]) -> list[dict]:
    """Three demo logins, one per role (spec section 3)."""
    hashed = hash_password(DEMO_PASSWORD)
    return [
        {
            "email": "admin@fleetguard.ai",
            "hashed_password": hashed,
            "full_name": "Priya Raghavan",
            "role": "manufacturer_admin",
            "customer_id": None,
            "is_active": True,
        },
        {
            "email": "fleet@sarthilogistics.in",
            "hashed_password": hashed,
            "full_name": "Devendra Nair",
            "role": "customer_admin",
            "customer_id": customers[0]["customer_id"],
            "is_active": True,
        },
        {
            "email": "viewer@bluelinecarriers.in",
            "hashed_password": hashed,
            "full_name": "Anita Deshmukh",
            "role": "viewer",
            "customer_id": customers[1]["customer_id"],
            "is_active": True,
        },
    ]


def make_vehicles(rng: random.Random, customers: list[dict], start: date) -> list[dict]:
    """Allocate vehicles across customers by their configured share."""
    shares = [c[4] for c in CUSTOMERS]
    total_share = sum(shares)
    counts = [round(N_VEHICLES * s / total_share) for s in shares]
    # Absorb any rounding drift into the largest fleet.
    counts[0] += N_VEHICLES - sum(counts)

    vehicles: list[dict] = []
    seq = 0
    for customer, count in zip(customers, counts, strict=True):
        for _ in range(count):
            model, variant, lo, hi = rng.choice(MODELS)
            km_per_day = round(rng.uniform(lo, hi), 1)
            age_days = rng.randint(400, 2200)
            registration = start - timedelta(days=age_days)
            start_odo = int(age_days * km_per_day * rng.uniform(0.88, 1.12))
            vehicles.append(
                {
                    "vin": f"MZ4A1{seq + 10000:05d}",
                    "customer_id": customer["customer_id"],
                    "model": model,
                    "variant": variant,
                    "region": customer["region"],
                    "registration_date": registration,
                    "total_km_driven": start_odo,
                    "avg_km_per_day": km_per_day,
                    "status": "active",
                    # working state, stripped before insert
                    "_odometer": start_odo,
                    "_profile": build_signal_profile(rng),
                }
            )
            seq += 1
    return vehicles


def _event_day(rng: random.Random, week_start: date, horizon: date) -> date:
    """A day inside the given week, never after the end of the record.

    Weeks are Monday-anchored, so the final week of the observation window runs
    up to six days past its end. An event landing there is dated in the future,
    and a workshop event that has not happened yet resets the part's clock in
    every read model that asks "when was this last replaced" - which then
    disagrees with a prediction scored from telemetry that stops at the end of
    the record.
    """
    return min(week_start + timedelta(days=rng.randint(0, 6)), horizon)


def simulate(
    rng: random.Random,
    vehicles: list[dict],
    weeks: list[date],
    hazard_stress: float = HAZARD_STRESS,
    hazard_age: float = HAZARD_AGE,
    hazard_intercept: float = HAZARD_INTERCEPT,
    horizon: date | None = None,
):
    """Walk the fleet week by week, emitting telemetry and workshop events."""
    horizon = horizon or weeks[-1] + timedelta(days=6)
    design_life = {p[0]: p[3] for p in PARTS}
    part_costs = {p[0]: (p[4], p[6]) for p in PARTS}

    telematics_rows: list[dict] = []
    job_cards: list[dict] = []

    stress_of_failures: list[float] = []
    stress_of_survivors: list[float] = []
    age_of_failures: list[float] = []
    noise_failures = 0
    model_failures = 0

    for vehicle in vehicles:
        vin = vehicle["vin"]
        km_per_day = vehicle["avg_km_per_day"]
        profile = vehicle["_profile"]
        odometer = vehicle["_odometer"]

        # Fit every tracked component, back-dating the fitment so that parts
        # already carry realistic wear when the observation window opens.
        part_state: dict[str, dict] = {}
        for part_code, life in design_life.items():
            initial_age = rng.uniform(0.02, 0.92)
            fitment_odo = max(0, int(odometer - initial_age * life))
            days_back = (odometer - fitment_odo) / max(km_per_day, 1.0)
            fitment_date = weeks[0] - timedelta(days=int(days_back))
            fitment_date = max(fitment_date, vehicle["registration_date"])
            part_state[part_code] = {
                "fitment_odo": fitment_odo,
                "preventive_at": rng.uniform(PREVENTIVE_MIN, PREVENTIVE_MAX),
            }
            job_cards.append(
                {
                    "vin": vin,
                    "part_code": part_code,
                    "event_date": fitment_date,
                    "odometer_reading": fitment_odo,
                    "event_type": "fitment",
                    "replaced": False,
                    "cost": 0,
                    "downtime_hours": 0.0,
                }
            )

        for week_index, week_start in enumerate(weeks):
            week_km = km_per_day * 7 * rng.uniform(0.72, 1.28)
            odometer += int(week_km)

            # 1. Base telemetry for the week: personality + slow drift + noise.
            signals: dict[str, float] = {}
            for signal in SIGNALS:
                spec = profile[signal]
                value = (
                    spec["base"]
                    + spec["drift"] * week_index
                    + rng.gauss(0.0, spec["noise"])
                )
                signals[signal] = clamp(value)

            # 2. Degradation feedback: a worn part raises its own precursors,
            #    in proportion to the weights that drive it.
            for part_code, state in part_state.items():
                age = (odometer - state["fitment_odo"]) / design_life[part_code]
                if age <= FEEDBACK_START:
                    continue
                intensity = clamp((age - FEEDBACK_START) / (1.0 - FEEDBACK_START))
                for signal, weight in PLANTED_WEIGHTS[part_code].items():
                    signals[signal] = clamp(
                        signals[signal] + FEEDBACK_STRENGTH * weight * intensity
                    )

            telematics_rows.append(
                {
                    "vin": vin,
                    "week_start_date": week_start,
                    "week_km": round(week_km, 1),
                    "odometer_km": odometer,
                    **{s: round(signals[s], 5) for s in SIGNALS},
                }
            )

            # 3. Resolve each component against the hazard model.
            for part_code, state in part_state.items():
                life = design_life[part_code]
                km_on_part = odometer - state["fitment_odo"]
                age = km_on_part / life
                stress = sum(
                    weight * signals[signal]
                    for signal, weight in PLANTED_WEIGHTS[part_code].items()
                )
                hazard = sigmoid(
                    hazard_stress * stress + hazard_age * age - hazard_intercept
                )

                failed = False
                by_noise = False
                if rng.random() < hazard:
                    failed = True
                elif rng.random() < NOISE_HAZARD:
                    failed = True
                    by_noise = True

                if failed:
                    unit_cost, labour_hours = part_costs[part_code]
                    event_day = _event_day(rng, week_start, horizon)
                    job_cards.append(
                        {
                            "vin": vin,
                            "part_code": part_code,
                            "event_date": event_day,
                            "odometer_reading": odometer,
                            "event_type": "failure",
                            "replaced": True,
                            "cost": round(unit_cost * rng.uniform(1.15, 1.55), 2),
                            "downtime_hours": round(
                                labour_hours * rng.uniform(2.0, 4.5), 1
                            ),
                        }
                    )
                    state["fitment_odo"] = odometer
                    state["preventive_at"] = rng.uniform(PREVENTIVE_MIN, PREVENTIVE_MAX)
                    stress_of_failures.append(stress)
                    age_of_failures.append(age)
                    if by_noise:
                        noise_failures += 1
                    else:
                        model_failures += 1
                    continue

                stress_of_survivors.append(stress)

                # 4. Preventive replacement before the part runs away past
                #    design life.
                if age >= state["preventive_at"]:
                    unit_cost, labour_hours = part_costs[part_code]
                    event_day = _event_day(rng, week_start, horizon)
                    job_cards.append(
                        {
                            "vin": vin,
                            "part_code": part_code,
                            "event_date": event_day,
                            "odometer_reading": odometer,
                            "event_type": "preventive",
                            "replaced": True,
                            "cost": round(unit_cost * rng.uniform(1.0, 1.15), 2),
                            "downtime_hours": round(
                                labour_hours * rng.uniform(1.0, 1.6), 1
                            ),
                        }
                    )
                    state["fitment_odo"] = odometer
                    state["preventive_at"] = rng.uniform(PREVENTIVE_MIN, PREVENTIVE_MAX)

        vehicle["total_km_driven"] = odometer

    diagnostics = {
        "model_failures": model_failures,
        "noise_failures": noise_failures,
        "mean_stress_failed": (
            sum(stress_of_failures) / len(stress_of_failures) if stress_of_failures else 0.0
        ),
        "mean_stress_survived": (
            sum(stress_of_survivors) / len(stress_of_survivors)
            if stress_of_survivors
            else 0.0
        ),
        "mean_age_failed": (
            sum(age_of_failures) / len(age_of_failures) if age_of_failures else 0.0
        ),
    }
    return telematics_rows, job_cards, diagnostics


def make_warranty_claims(
    rng: random.Random,
    session,
    vehicles_by_vin: dict[str, dict],
) -> list[dict]:
    """Claim a subset of failures that fall inside the warranty envelope."""
    rows = session.execute(
        select(
            JobCard.job_card_id,
            JobCard.vin,
            JobCard.part_code,
            JobCard.event_date,
            JobCard.odometer_reading,
            JobCard.cost,
        ).where(JobCard.event_type == "failure")
    ).all()

    claims: list[dict] = []
    for job_card_id, vin, part_code, event_date, odometer, cost in rows:
        vehicle = vehicles_by_vin[vin]
        in_warranty_time = (
            event_date - vehicle["registration_date"]
        ).days <= WARRANTY_YEARS * 365
        in_warranty_km = odometer <= WARRANTY_KM
        if not (in_warranty_time and in_warranty_km):
            continue
        if rng.random() > WARRANTY_CLAIM_RATE:
            continue
        claims.append(
            {
                "job_card_id": job_card_id,
                "vin": vin,
                "part_code": part_code,
                "claim_date": event_date + timedelta(days=rng.randint(1, 21)),
                "claim_amount": round(float(cost) * rng.uniform(0.55, 0.95), 2),
                "status": rng.choices(
                    ["approved", "rejected", "pending"], weights=[0.68, 0.14, 0.18]
                )[0],
            }
        )
    return claims


def wipe(session) -> None:
    """Clear generated data so the script is idempotent and re-runnable.

    Order matters: everything scored or actioned on top of the old fleet has
    to go before the fleet itself, or foreign keys refuse the delete. A new
    fleet invalidates every prediction and rule derived from the old one.
    """
    for model in (
        WorkOrder,
        Notification,
        Prediction,
        RuleSignal,
        Rule,
        AuditLog,
        WarrantyClaim,
        JobCard,
        TelematicsWeekly,
        Vehicle,
        Part,
        User,
        Customer,
    ):
        session.execute(delete(model))
    session.commit()


def chunked_insert(session, model, rows: list[dict], size: int = 2000) -> None:
    for start in range(0, len(rows), size):
        session.execute(insert(model), rows[start : start + size])
    session.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the synthetic fleet dataset.")
    parser.add_argument("--seed", type=int, default=settings.SEED)
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="Last observation week (YYYY-MM-DD). Defaults to this week.",
    )
    # Exposed so the hazard model can be tuned against the spec's three
    # simultaneous targets (failure count, precision band, signal recovery)
    # without editing the module every time.
    parser.add_argument("--hazard-stress", type=float, default=HAZARD_STRESS)
    parser.add_argument("--hazard-age", type=float, default=HAZARD_AGE)
    parser.add_argument("--hazard-intercept", type=float, default=HAZARD_INTERCEPT)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    end_week = most_recent_monday(args.end_date or date.today())
    weeks = [end_week - timedelta(weeks=N_WEEKS - 1 - i) for i in range(N_WEEKS)]

    print(f"Seed {args.seed}. Observation window {weeks[0]} to {weeks[-1]}.")
    print(f"Hazard: stress {args.hazard_stress}, age {args.hazard_age}, intercept {args.hazard_intercept}.")

    customers = make_customers()
    users = make_users(customers)
    vehicles = make_vehicles(rng, customers, weeks[0])
    parts = [
        {
            "part_code": code,
            "part_name": name,
            "category": category,
            "design_life_km": life,
            "unit_cost": cost,
            "lead_time_days": lead,
            "labour_hours": labour,
        }
        for code, name, category, life, cost, lead, labour in PARTS
    ]

    print(f"Simulating {len(vehicles)} vehicles x {len(parts)} components x {N_WEEKS} weeks...")
    telematics_rows, job_cards, diagnostics = simulate(
        rng,
        vehicles,
        weeks,
        hazard_stress=args.hazard_stress,
        hazard_age=args.hazard_age,
        hazard_intercept=args.hazard_intercept,
        # No workshop event may be dated after the end of the record.
        horizon=args.end_date or date.today(),
    )

    vehicles_by_vin = {v["vin"]: v for v in vehicles}
    vehicle_rows = [
        {k: v for k, v in vehicle.items() if not k.startswith("_")} for vehicle in vehicles
    ]

    session = SessionLocal()
    try:
        wipe(session)
        chunked_insert(session, Customer, customers)
        chunked_insert(session, User, users)
        chunked_insert(session, Part, parts)
        chunked_insert(session, Vehicle, vehicle_rows)
        chunked_insert(session, TelematicsWeekly, telematics_rows)
        chunked_insert(session, JobCard, job_cards)
        claims = make_warranty_claims(rng, session, vehicles_by_vin)
        chunked_insert(session, WarrantyClaim, claims)
    finally:
        session.close()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "planted_weights.json").write_text(
        json.dumps(PLANTED_WEIGHTS, indent=2), encoding="utf-8"
    )

    failures = diagnostics["model_failures"] + diagnostics["noise_failures"]
    preventive = sum(1 for jc in job_cards if jc["event_type"] == "preventive")
    noise_share = diagnostics["noise_failures"] / failures if failures else 0.0

    print()
    print("Seeded:")
    print(f"  customers            {len(customers)}")
    print(f"  users                {len(users)}")
    print(f"  parts                {len(parts)}")
    print(f"  vehicles             {len(vehicle_rows)}")
    print(f"  telematics weeks     {len(telematics_rows)}")
    print(f"  job cards            {len(job_cards)}")
    print(f"  warranty claims      {len(claims)}")
    print()
    print("Failure model:")
    print(f"  failures             {failures}   (target band 1000-1500)")
    print(f"  from signals         {diagnostics['model_failures']}")
    print(f"  random / unexplained {diagnostics['noise_failures']}  ({noise_share:.1%} - target ~10%)")
    print(f"  preventive swaps     {preventive}")
    print()
    print("Discrimination check:")
    print(f"  mean stress, failed weeks    {diagnostics['mean_stress_failed']:.4f}")
    print(f"  mean stress, survived weeks  {diagnostics['mean_stress_survived']:.4f}")
    print(f"  mean age at failure          {diagnostics['mean_age_failed']:.3f} of design life")
    print()
    print(f"Ground truth written to {DATA_DIR / 'planted_weights.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
