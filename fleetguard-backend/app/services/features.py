from __future__ import annotations

import pandas as pd
from sqlalchemy.engine import Engine

from app.config import LABEL_HORIZON_DAYS, ROLLING_WEEKS, SIGNALS

_cache: dict[str, pd.DataFrame] = {}


def invalidate_cache() -> None:
    _cache.clear()


def load_raw(engine: Engine) -> dict[str, pd.DataFrame]:
    if "vehicles" in _cache:
        return {k: _cache[k] for k in ("vehicles", "parts", "jobcards", "telematics")}

    vehicles = pd.read_sql("SELECT * FROM vehicle_master", engine)
    parts = pd.read_sql("SELECT * FROM part_master", engine)
    jobcards = pd.read_sql("SELECT * FROM job_cards", engine)
    telematics = pd.read_sql("SELECT * FROM telematics_weekly", engine)

    if not jobcards.empty:
        jobcards["failure_date"] = pd.to_datetime(jobcards["failure_date"])
    if not telematics.empty:
        telematics["week_start_date"] = pd.to_datetime(telematics["week_start_date"])
    if not vehicles.empty:
        vehicles["registration_date"] = pd.to_datetime(vehicles["registration_date"])

    _cache.update(vehicles=vehicles, parts=parts, jobcards=jobcards, telematics=telematics)
    return {"vehicles": vehicles, "parts": parts, "jobcards": jobcards, "telematics": telematics}


def build_features(engine: Engine) -> pd.DataFrame:
    if "features" in _cache:
        return _cache["features"]

    raw = load_raw(engine)
    tel, jobs, parts, veh = raw["telematics"], raw["jobcards"], raw["parts"], raw["vehicles"]

    if tel.empty or parts.empty:
        _cache["features"] = pd.DataFrame()
        return _cache["features"]

    tel = tel.sort_values(["vin", "week_start_date"]).copy()
    for sig in SIGNALS:
        tel[sig] = (
            tel.groupby("vin")[sig]
            .transform(lambda s: s.rolling(ROLLING_WEEKS, min_periods=1).mean())
            .clip(0, 1)
        )

    tel = tel[["vin", "week_start_date", "odometer_km", "week_km"] + SIGNALS]
    tel = tel.sort_values("week_start_date").reset_index(drop=True)

    frames = []
    for part in parts.itertuples():
        block = tel.copy()
        block["part_code"] = part.part_code
        block["design_life_km"] = part.design_life_km

        part_jobs = jobs[jobs["part_code"] == part.part_code] if not jobs.empty else jobs

        if part_jobs is None or part_jobs.empty:
            block["last_replacement_km"] = 0.0
            block["next_failure_date"] = pd.NaT
            block["label_failed_30d"] = 0
        else:
            replaced = (
                part_jobs[part_jobs["replaced"].astype(bool)][
                    ["vin", "failure_date", "odometer_at_failure"]
                ]
                .sort_values("failure_date")
                .reset_index(drop=True)
            )
            if replaced.empty:
                block["last_replacement_km"] = 0.0
            else:
                block = pd.merge_asof(
                    block,
                    replaced,
                    left_on="week_start_date",
                    right_on="failure_date",
                    by="vin",
                    direction="backward",
                )
                block["last_replacement_km"] = block["odometer_at_failure"].fillna(0.0)
                block = block.drop(columns=["odometer_at_failure", "failure_date"])

            failures_only = part_jobs[part_jobs.get("event_type", "failure") == "failure"]
            upcoming = (
                failures_only[["vin", "failure_date"]]
                .sort_values("failure_date")
                .reset_index(drop=True)
            )
            block = block.sort_values("week_start_date").reset_index(drop=True)
            block = pd.merge_asof(
                block,
                upcoming,
                left_on="week_start_date",
                right_on="failure_date",
                by="vin",
                direction="forward",
            )
            block = block.rename(columns={"failure_date": "next_failure_date"})
            gap = (block["next_failure_date"] - block["week_start_date"]).dt.days
            block["label_failed_30d"] = ((gap >= 0) & (gap <= LABEL_HORIZON_DAYS)).astype(int)

        block["km_on_part"] = (block["odometer_km"] - block["last_replacement_km"]).clip(lower=0)
        block["age_fraction"] = (block["km_on_part"] / block["design_life_km"]).clip(0, 1.3)
        frames.append(block)

    out = pd.concat(frames, ignore_index=True)
    out = out.merge(
        veh[["vin", "model", "region", "avg_km_per_day", "fleet_operator"]], on="vin", how="left"
    )
    out = out.sort_values(["part_code", "vin", "week_start_date"]).reset_index(drop=True)

    _cache["features"] = out
    return out


def latest_week(feats: pd.DataFrame) -> pd.Timestamp:
    return feats["week_start_date"].max()


def current_slice(feats: pd.DataFrame) -> pd.DataFrame:
    return feats[feats["week_start_date"] == latest_week(feats)].copy()