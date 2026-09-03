"""Remaining useful life (spec section 6.6).

Fit a line through the last 26 weeks of health index against km_on_part and
project it forward to the failure threshold (health index 30). The remaining
kilometres come from that intercept; the days come from dividing by the
vehicle's own observed km/day rather than a fleet average, because a long-haul
tractor and a city distribution truck burn through the same part at very
different rates.

Confidence is the fit's R-squared, reported honestly - a noisy history should
produce a low-confidence number, not a hidden one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from app.constants import FAILURE_THRESHOLD_INDEX, RUL_FIT_WEEKS

# Guard rails. A nearly flat fit can project a comically distant threshold;
# capping keeps the UI honest instead of promising 40 years of brake pads.
MAX_RUL_DAYS = 1825.0
PROJECTION_POINTS = 8


@dataclass
class RulResult:
    rul_km: float
    rul_days: float
    model_confidence: float
    degradation_trend: float
    method: str
    curve: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rul_km": self.rul_km,
            "rul_days": self.rul_days,
            "model_confidence": self.model_confidence,
            "degradation_trend": self.degradation_trend,
            "method": self.method,
            "curve": self.curve,
        }


def estimate_rul(
    history: pd.DataFrame,
    design_life_km: float,
    avg_km_per_day: float,
    fit_weeks: int = RUL_FIT_WEEKS,
) -> RulResult:
    """Project one component's health forward to the failure threshold.

    `history` needs km_on_part and health_index, oldest first.
    """
    window = history.tail(fit_weeks)
    km_per_day = max(float(avg_km_per_day), 1.0)

    if window.empty:
        return RulResult(0.0, 0.0, 0.0, 0.0, "no_history", [])

    km = window["km_on_part"].to_numpy(dtype=float)
    health = window["health_index"].to_numpy(dtype=float)
    current_km = float(km[-1])
    current_health = float(health[-1])

    observed = [
        {"km_on_part": round(float(k), 1), "health_index": round(float(h), 2), "projected": False}
        for k, h in zip(km, health, strict=True)
    ]

    # A flat odometer or too few points cannot support a regression.
    if len(window) < 3 or np.isclose(km.max(), km.min()):
        return _design_life_fallback(
            current_km, current_health, design_life_km, km_per_day, observed
        )

    fit = stats.linregress(km, health)
    slope = float(fit.slope)
    intercept = float(fit.intercept)
    confidence = float(fit.rvalue**2)

    # Health that is flat or improving gives no crossing point to project to.
    if slope >= -1e-9:
        return _design_life_fallback(
            current_km, current_health, design_life_km, km_per_day, observed, confidence
        )

    km_at_threshold = (FAILURE_THRESHOLD_INDEX - intercept) / slope
    rul_km = max(0.0, km_at_threshold - current_km)
    rul_days = min(rul_km / km_per_day, MAX_RUL_DAYS)
    rul_km = min(rul_km, rul_days * km_per_day)

    curve = observed + _projected_points(current_km, rul_km, slope, intercept)

    return RulResult(
        rul_km=round(rul_km, 1),
        rul_days=round(rul_days, 1),
        model_confidence=round(confidence, 4),
        # Health points lost per 1,000 km reads better than per km.
        degradation_trend=round(-slope * 1000.0, 4),
        method="regression",
        curve=curve,
    )


def _projected_points(
    current_km: float,
    rul_km: float,
    slope: float,
    intercept: float,
) -> list[dict]:
    if rul_km <= 0:
        return []
    steps = np.linspace(current_km, current_km + rul_km, PROJECTION_POINTS + 1)[1:]
    return [
        {
            "km_on_part": round(float(k), 1),
            "health_index": round(float(max(0.0, slope * k + intercept)), 2),
            "projected": True,
        }
        for k in steps
    ]


def _design_life_fallback(
    current_km: float,
    current_health: float,
    design_life_km: float,
    km_per_day: float,
    observed: list[dict],
    confidence: float = 0.0,
) -> RulResult:
    """When the fit is unusable, fall back to plain design life.

    Reported with a distinct method name and a low confidence so the UI can
    say why the number is soft, rather than presenting a guess as a projection.
    """
    rul_km = max(0.0, float(design_life_km) - current_km)
    rul_days = min(rul_km / km_per_day, MAX_RUL_DAYS)
    rul_km = min(rul_km, rul_days * km_per_day)
    return RulResult(
        rul_km=round(rul_km, 1),
        rul_days=round(rul_days, 1),
        model_confidence=round(min(confidence, 0.25), 4),
        degradation_trend=0.0,
        method="design_life_fallback",
        curve=observed,
    )
