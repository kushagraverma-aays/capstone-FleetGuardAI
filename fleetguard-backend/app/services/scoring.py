"""Health index, failure probability and risk tier (spec sections 6.5, 6.7).

There is exactly one quantity here that matters:

    health_index = 100 - 70*age_fraction - 30*stress   (clamped 0-100)
    failure_probability = 1 - health_index/100

Both the probability view and the RUL view derive from it, which is the whole
reason they can never contradict each other. Nothing else in the codebase is
allowed to invent a second definition of risk.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.constants import (
    AMBER_THRESHOLD,
    RED_THRESHOLD,
    URGENT_RUL_DAYS,
    WEIGHT_AGE,
    WEIGHT_STRESS,
)


@dataclass(frozen=True)
class RiskAssessment:
    health_index: float
    failure_probability: float
    risk_tier: str
    escalated: bool
    escalation_reason: str | None


def stress_from_weights(signals: dict[str, float], weights: dict[str, float]) -> float:
    """Weighted sum of the rule's signals. Weights sum to 1, so stress is 0-1."""
    return float(sum(weights.get(s, 0.0) * signals.get(s, 0.0) for s in weights))


def health_index(age_fraction: float, stress: float) -> float:
    raw = 100.0 - WEIGHT_AGE * age_fraction - WEIGHT_STRESS * stress
    return float(min(100.0, max(0.0, raw)))


def failure_probability(health: float) -> float:
    return round(1.0 - health / 100.0, 6)


def risk_tier(probability: float) -> str:
    if probability >= RED_THRESHOLD:
        return "RED"
    if probability >= AMBER_THRESHOLD:
        return "AMBER"
    return "GREEN"


def assess(age_fraction: float, stress: float, rul_days: float | None) -> RiskAssessment:
    """Score one (vehicle, component), including urgency escalation.

    Urgency is not only a function of likelihood: a component a week from the
    end of its life is actionable today even if its probability reads AMBER.
    """
    health = health_index(age_fraction, stress)
    probability = failure_probability(health)
    tier = risk_tier(probability)

    escalated = False
    reason: str | None = None
    if rul_days is not None and 0 <= rul_days <= URGENT_RUL_DAYS and tier != "RED":
        escalated = True
        reason = (
            f"Escalated to RED: {rul_days:.0f} days of useful life remain "
            f"(threshold {URGENT_RUL_DAYS} days), despite a "
            f"{probability:.0%} failure probability."
        )
        tier = "RED"

    return RiskAssessment(
        health_index=round(health, 4),
        failure_probability=probability,
        risk_tier=tier,
        escalated=escalated,
        escalation_reason=reason,
    )


def stress_frame(features: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """The rule's own output: the weighted signal sum, on a 0-1 scale.

    This is the quantity the deployed formula describes
    (`failure_probability = 0.28 coolant_temp_variance + ...`), and it is what
    the back-test replays. It deliberately excludes age: a rule is a statement
    about telematics signals, and mixing age back in would make it alert on
    every part approaching design life, most of which get replaced on schedule
    rather than failing.
    """
    stress = np.zeros(len(features), dtype=float)
    for signal, weight in weights.items():
        if signal in features.columns:
            stress = stress + weight * features[signal].to_numpy(dtype=float)
    return pd.Series(np.clip(stress, 0.0, 1.0), index=features.index)


def probability_frame(features: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Vectorised health-index failure probability for a whole feature table.

    Algebraically identical to assess(): with health clamped to 0-100,
    probability is 0.70*age + 0.30*stress clamped to 0-1.
    """
    stress = stress_frame(features, weights).to_numpy(dtype=float)
    age = features["age_fraction"].to_numpy(dtype=float)
    probability = (WEIGHT_AGE * age + WEIGHT_STRESS * stress) / 100.0
    return pd.Series(np.clip(probability, 0.0, 1.0), index=features.index)


def cross_check_sentence(
    probability: float,
    tier: str,
    rul_days: float,
    rul_km: float,
    part_name: str,
) -> str:
    """The sentence every detail view shows to tie the two views together.

    Spec 6.5 requires each detail response to reference the other view's
    numbers explicitly, so a user can see they agree rather than taking it on
    trust.
    """
    return (
        f"{part_name} scores {probability:.0%} failure probability ({tier}); "
        f"the same health index projects {rul_km:,.0f} km / {rul_days:.0f} days "
        f"of useful life remaining. Both figures derive from one health index, "
        f"so they move together."
    )
