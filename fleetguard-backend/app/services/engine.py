from __future__ import annotations

import numpy as np
import pandas as pd

from app.config import (
    AMBER_THRESHOLD,
    FAILURE_THRESHOLD_INDEX,
    RED_THRESHOLD,
    URGENT_RUL_DAYS,
    SIGNAL_LABELS,
    TREND_WEEKS,
    WEIGHT_AGE,
    WEIGHT_STRESS,
)

CURVE_HISTORY_WEEKS = 26
CURVE_PROJECTION_POINTS = 8


def stress_series(df: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    total = sum(weights.values()) or 1.0
    out = pd.Series(0.0, index=df.index)
    for sig, w in weights.items():
        if sig in df.columns:
            out = out + df[sig] * (w / total)
    return out.clip(0, 1)


def score_frame(df: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    out = df.copy()
    out["stress"] = stress_series(out, weights)
    health = 100.0 - WEIGHT_AGE * out["age_fraction"] - WEIGHT_STRESS * out["stress"]
    out["health_index"] = health.clip(0.0, 100.0)
    out["failure_probability"] = (1.0 - out["health_index"] / 100.0).clip(0.01, 0.99)
    return out


def risk_tier(probability: float, rul_days: int | None = None) -> str:
    if rul_days is not None and rul_days <= URGENT_RUL_DAYS:
        return "RED"
    if probability >= RED_THRESHOLD:
        return "RED"
    if probability >= AMBER_THRESHOLD:
        return "AMBER"
    return "GREEN"


def is_escalated(probability: float, rul_days: int | None) -> bool:
    return (
        rul_days is not None
        and rul_days <= URGENT_RUL_DAYS
        and probability < RED_THRESHOLD
    )


def drivers_for_row(row: pd.Series, weights: dict[str, float]) -> list[dict]:
    total_w = sum(weights.values()) or 1.0
    contributions = {}
    for sig, w in weights.items():
        if sig in row.index:
            contributions[sig] = float(row[sig]) * (w / total_w)
    total_c = sum(contributions.values()) or 1.0
    out = [
        {
            "signal": sig,
            "label": SIGNAL_LABELS.get(sig, sig),
            "value": round(float(row.get(sig, 0.0)), 4),
            "share": round(value / total_c, 4),
        }
        for sig, value in contributions.items()
    ]
    out.sort(key=lambda d: d["share"], reverse=True)
    return out


def probability_trend(history: pd.DataFrame, weeks: int = TREND_WEEKS) -> list[dict]:
    tail = history.tail(weeks)
    return [
        {
            "week": row.week_start_date.strftime("%Y-%m-%d"),
            "probability": round(float(row.failure_probability), 4),
        }
        for row in tail.itertuples()
    ]


def estimate_rul(history: pd.DataFrame, design_life_km: float, avg_km_per_day: float) -> dict:
    hist = history.tail(CURVE_HISTORY_WEEKS)
    km = hist["km_on_part"].to_numpy(dtype=float)
    health = hist["health_index"].to_numpy(dtype=float)

    health_now = float(health[-1])
    km_now = float(km[-1])
    fallback_slope = -WEIGHT_AGE / max(design_life_km, 1.0)

    slope = fallback_slope
    r2 = 0.0
    if len(km) >= 4 and np.ptp(km) > 1.0:
        slope_fit, intercept = np.polyfit(km, health, 1)
        predicted = slope_fit * km + intercept
        ss_res = float(np.sum((health - predicted) ** 2))
        ss_tot = float(np.sum((health - health.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        if slope_fit < -1e-9:
            slope = float(slope_fit)

    remaining_index = max(health_now - FAILURE_THRESHOLD_INDEX, 0.0)
    rul_km = remaining_index / abs(slope) if slope < 0 else 0.0
    rul_km = float(np.clip(rul_km, 0.0, design_life_km * 1.5))

    daily = max(avg_km_per_day, 1.0)
    rul_days = int(round(rul_km / daily))
    confidence = float(np.clip(55.0 + 40.0 * max(r2, 0.0), 55.0, 97.0))
    trend_per_month = float(slope * daily * 30.0)

    curve = [
        {"km": round(float(k), 1), "health": round(float(h), 2), "projected": False}
        for k, h in zip(km, health)
    ]
    if rul_km > 0:
        for i in range(1, CURVE_PROJECTION_POINTS + 1):
            step = rul_km * i / CURVE_PROJECTION_POINTS
            curve.append(
                {
                    "km": round(km_now + step, 1),
                    "health": round(max(health_now + slope * step, 0.0), 2),
                    "projected": True,
                }
            )

    return {
        "rul_km": round(rul_km, 1),
        "rul_days": rul_days,
        "model_confidence": round(confidence, 1),
        "degradation_trend": round(trend_per_month, 2),
        "health_index": round(health_now, 2),
        "curve": curve,
    }


def failure_window(rul_days: int) -> tuple[int, int]:
    if rul_days <= 0:
        return 0, 7
    return max(int(round(rul_days * 0.75)), 1), int(round(rul_days * 1.3))