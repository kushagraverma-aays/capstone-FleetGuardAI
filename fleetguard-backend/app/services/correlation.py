"""Signal ranking (spec section 6.2).

Point-biserial correlation is the primary ranking. It is the correct measure
for a continuous variable against a binary outcome, and scipy implements it
directly. A standardised logistic regression is run alongside as a cross-check:
correlation is univariate and can be fooled by two signals carrying the same
information, whereas the regression coefficients see them together.

Negative correlations are floored at zero. A negative value would mean the
signal protects against failure, which is not a meaningful input to a risk
score and would flip the sign of a weight downstream.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.constants import SIGNAL_LABELS, SIGNALS


@dataclass(frozen=True)
class SignalCorrelation:
    signal: str
    label: str
    correlation: float
    raw_correlation: float
    p_value: float
    logit_coefficient: float
    mean_when_failed: float
    mean_when_healthy: float

    def to_dict(self) -> dict:
        return asdict(self)


def rank_signals(features: pd.DataFrame) -> list[SignalCorrelation]:
    """Rank the nine signals for one component, strongest first."""
    if features.empty or "failed_within_horizon" not in features:
        return []

    labels = features["failed_within_horizon"].to_numpy()
    # A correlation needs both classes present; with one class it is undefined.
    if labels.sum() == 0 or labels.sum() == len(labels):
        return []

    logit_coefficients = _logit_coefficients(features, labels)

    results: list[SignalCorrelation] = []
    for signal in SIGNALS:
        values = features[signal].to_numpy(dtype=float)
        if np.allclose(values, values[0]):
            raw, p_value = 0.0, 1.0
        else:
            raw, p_value = stats.pointbiserialr(labels, values)
            if np.isnan(raw):
                raw, p_value = 0.0, 1.0

        results.append(
            SignalCorrelation(
                signal=signal,
                label=SIGNAL_LABELS[signal],
                correlation=round(max(0.0, float(raw)), 6),
                raw_correlation=round(float(raw), 6),
                p_value=round(float(p_value), 8),
                logit_coefficient=round(float(logit_coefficients.get(signal, 0.0)), 6),
                mean_when_failed=round(float(values[labels == 1].mean()), 6),
                mean_when_healthy=round(float(values[labels == 0].mean()), 6),
            )
        )

    results.sort(key=lambda r: r.correlation, reverse=True)
    return results


def _logit_coefficients(features: pd.DataFrame, labels: np.ndarray) -> dict[str, float]:
    """Standardised logistic regression coefficients, as a cross-check.

    Standardising first is what makes the coefficients comparable to each
    other; on raw scales a signal would look important merely for having a
    wider range.
    """
    matrix = features[SIGNALS].to_numpy(dtype=float)
    try:
        scaled = StandardScaler().fit_transform(matrix)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            model = LogisticRegression(max_iter=1000, C=1.0, solver="lbfgs")
            model.fit(scaled, labels)
        return dict(zip(SIGNALS, model.coef_[0], strict=True))
    except Exception:
        # The cross-check is advisory; never let it break the ranking.
        return {}


def top_signals(
    correlations: list[SignalCorrelation],
    limit: int,
    minimum: float = 0.0,
) -> list[SignalCorrelation]:
    return [c for c in correlations if c.correlation >= minimum][:limit]
