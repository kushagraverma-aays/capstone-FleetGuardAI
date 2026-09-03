"""Feature table construction (spec section 6.1).

One row per (vin, part_code, week) carrying:
  * the nine telematics signals smoothed with a 4-week rolling mean,
  * km_on_part - the odometer since this part was last installed,
  * age_fraction - km_on_part over the design life,
  * failed_within_horizon - the binary label.

These are plain functions over a SQLAlchemy session and pandas frames, with no
FastAPI in sight, so the same code backs the REST API, the agent tools and the
offline validation script.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import LABEL_HORIZON_DAYS, ROLLING_WEEKS, SIGNALS
from app.models import JobCard, Part, TelematicsWeekly

# Every workshop event installs a fresh part, so all three reset the part clock:
# a fitment is the initial install, a failure is replaced on the spot, and a
# preventive swap is a planned replacement.
INSTALL_EVENTS = ("fitment", "failure", "preventive")


def load_telematics(session: Session) -> pd.DataFrame:
    columns = [
        TelematicsWeekly.vin,
        TelematicsWeekly.week_start_date,
        TelematicsWeekly.week_km,
        TelematicsWeekly.odometer_km,
        *[getattr(TelematicsWeekly, signal) for signal in SIGNALS],
    ]
    frame = pd.DataFrame(
        session.execute(select(*columns)).all(),
        columns=["vin", "week_start_date", "week_km", "odometer_km", *SIGNALS],
    )
    if frame.empty:
        return frame
    frame["week_start_date"] = pd.to_datetime(frame["week_start_date"])
    return frame.sort_values(["vin", "week_start_date"]).reset_index(drop=True)


def load_job_cards(session: Session) -> pd.DataFrame:
    frame = pd.DataFrame(
        session.execute(
            select(
                JobCard.vin,
                JobCard.part_code,
                JobCard.event_date,
                JobCard.odometer_reading,
                JobCard.event_type,
            )
        ).all(),
        columns=["vin", "part_code", "event_date", "odometer_reading", "event_type"],
    )
    if frame.empty:
        return frame
    frame["event_date"] = pd.to_datetime(frame["event_date"])
    return frame


def load_parts(session: Session) -> pd.DataFrame:
    return pd.DataFrame(
        session.execute(
            select(Part.part_code, Part.part_name, Part.category, Part.design_life_km)
        ).all(),
        columns=["part_code", "part_name", "category", "design_life_km"],
    )


def smooth_signals(telematics: pd.DataFrame) -> pd.DataFrame:
    """4-week rolling mean per vehicle.

    Weekly telematics is noisy enough that a single bad week can flip a
    ranking; smoothing is what makes the correlations stable.
    """
    frame = telematics.copy()
    grouped = frame.groupby("vin", sort=False)[SIGNALS]
    frame[SIGNALS] = grouped.transform(
        lambda s: s.rolling(ROLLING_WEEKS, min_periods=1).mean()
    )
    return frame


def build_feature_table(
    session: Session,
    part_codes: list[str] | None = None,
) -> pd.DataFrame:
    """Cross the weekly telemetry with every tracked component."""
    telematics = load_telematics(session)
    job_cards = load_job_cards(session)
    parts = load_parts(session)

    if telematics.empty or parts.empty:
        return pd.DataFrame()

    if part_codes:
        parts = parts[parts["part_code"].isin(part_codes)]
        job_cards = job_cards[job_cards["part_code"].isin(part_codes)]

    smoothed = smooth_signals(telematics)

    # Cross join: every vehicle-week is evaluated against every component.
    features = smoothed.merge(parts[["part_code", "design_life_km"]], how="cross")
    features = features.sort_values(["week_start_date", "vin", "part_code"]).reset_index(
        drop=True
    )

    features = _attach_km_on_part(features, job_cards)
    features = _attach_label(features, job_cards)

    features["age_fraction"] = features["km_on_part"] / features["design_life_km"]
    return features


def _attach_km_on_part(features: pd.DataFrame, job_cards: pd.DataFrame) -> pd.DataFrame:
    """Odometer since the current part was installed.

    Without fitment records this is uncomputable, and RUL - which is about the
    part, not the truck - would be meaningless.
    """
    installs = (
        job_cards[job_cards["event_type"].isin(INSTALL_EVENTS)]
        .loc[:, ["vin", "part_code", "event_date", "odometer_reading"]]
        .rename(columns={"odometer_reading": "install_odometer"})
        .sort_values("event_date")
        .reset_index(drop=True)
    )

    if installs.empty:
        features["install_odometer"] = 0
        features["km_on_part"] = features["odometer_km"]
        return features

    merged = pd.merge_asof(
        features,
        installs,
        left_on="week_start_date",
        right_on="event_date",
        by=["vin", "part_code"],
        direction="backward",
        allow_exact_matches=True,
    )
    merged["install_odometer"] = merged["install_odometer"].fillna(0)
    merged["km_on_part"] = (
        merged["odometer_km"] - merged["install_odometer"]
    ).clip(lower=0)
    return merged.drop(columns=["event_date"])


def _attach_label(features: pd.DataFrame, job_cards: pd.DataFrame) -> pd.DataFrame:
    """failed_within_horizon: does a real failure follow inside 90 days?

    Only event_type == 'failure' counts. Preventive swaps and fitments are
    planned work, and labelling them as failures would teach the model that
    good maintenance is a fault.
    """
    failures = (
        job_cards[job_cards["event_type"] == "failure"]
        .loc[:, ["vin", "part_code", "event_date"]]
        .rename(columns={"event_date": "next_failure_date"})
        .sort_values("next_failure_date")
        .reset_index(drop=True)
    )

    if failures.empty:
        features["next_failure_date"] = pd.NaT
        features["days_to_failure"] = np.nan
        features["failed_within_horizon"] = 0
        return features

    merged = pd.merge_asof(
        features,
        failures,
        left_on="week_start_date",
        right_on="next_failure_date",
        by=["vin", "part_code"],
        direction="forward",
        allow_exact_matches=True,
    )
    merged["days_to_failure"] = (
        merged["next_failure_date"] - merged["week_start_date"]
    ).dt.days
    merged["failed_within_horizon"] = (
        merged["days_to_failure"].between(0, LABEL_HORIZON_DAYS).astype(int)
    )
    return merged


def latest_week(features: pd.DataFrame) -> pd.Timestamp | None:
    if features.empty:
        return None
    return features["week_start_date"].max()
