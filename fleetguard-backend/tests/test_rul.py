"""Remaining useful life projection - spec 6.6."""

from __future__ import annotations

import pandas as pd
import pytest

from app.constants import FAILURE_THRESHOLD_INDEX
from app.services.rul import MAX_RUL_DAYS, estimate_rul


def history(km: list[float], health: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"km_on_part": km, "health_index": health})


def test_a_clean_decline_projects_to_the_failure_threshold():
    # Health falls 1 point per 1,000 km, currently 50 at 50,000 km.
    km = [i * 1000.0 for i in range(51)]
    health = [100.0 - i for i in range(51)]
    result = estimate_rul(history(km, health), design_life_km=100_000, avg_km_per_day=100)

    # 50 -> 30 is 20 more points, so 20,000 km, at 100 km/day = 200 days.
    assert result.method == "regression"
    assert result.rul_km == pytest.approx(20_000, rel=0.02)
    assert result.rul_days == pytest.approx(200, rel=0.02)


def test_confidence_is_r_squared_and_near_one_for_a_perfect_line():
    km = [i * 1000.0 for i in range(30)]
    health = [100.0 - i for i in range(30)]
    result = estimate_rul(history(km, health), 100_000, 100)
    assert result.model_confidence == pytest.approx(1.0, abs=1e-6)


def test_a_noisy_history_reports_lower_confidence():
    km = [i * 1000.0 for i in range(30)]
    health = [100.0 - i + (8 if i % 2 else -8) for i in range(30)]
    result = estimate_rul(history(km, health), 100_000, 100)
    assert result.model_confidence < 0.8


def test_degradation_trend_is_health_lost_per_1000km():
    km = [i * 1000.0 for i in range(30)]
    health = [100.0 - 2 * i for i in range(30)]
    result = estimate_rul(history(km, health), 100_000, 100)
    assert result.degradation_trend == pytest.approx(2.0, rel=1e-3)


def test_flat_health_falls_back_to_design_life():
    km = [i * 1000.0 for i in range(30)]
    health = [80.0] * 30
    result = estimate_rul(history(km, health), design_life_km=100_000, avg_km_per_day=100)
    assert result.method == "design_life_fallback"
    # 29,000 km on the part, 71,000 km of design life left.
    assert result.rul_km == pytest.approx(71_000, rel=0.01)
    assert result.model_confidence <= 0.25


def test_improving_health_also_falls_back_rather_than_projecting_backwards():
    km = [i * 1000.0 for i in range(30)]
    health = [50.0 + i for i in range(30)]
    result = estimate_rul(history(km, health), 100_000, 100)
    assert result.method == "design_life_fallback"
    assert result.rul_km >= 0


def test_a_part_already_past_the_threshold_has_no_life_left():
    km = [i * 1000.0 for i in range(40)]
    health = [100.0 - 2.5 * i for i in range(40)]  # crosses 30 well before the end
    result = estimate_rul(history(km, health), 100_000, 100)
    assert result.rul_km == 0.0
    assert result.rul_days == 0.0


def test_too_few_points_cannot_support_a_regression():
    result = estimate_rul(history([1000.0, 2000.0], [90.0, 80.0]), 100_000, 100)
    assert result.method == "design_life_fallback"


def test_empty_history_is_handled():
    result = estimate_rul(history([], []), 100_000, 100)
    assert result.method == "no_history"
    assert result.rul_days == 0.0


def test_a_stationary_odometer_cannot_support_a_regression():
    result = estimate_rul(history([5000.0] * 10, [90.0, 88, 86, 84, 82, 80, 78, 76, 74, 72]), 100_000, 100)
    assert result.method == "design_life_fallback"


def test_a_nearly_flat_decline_is_capped_rather_than_promising_decades():
    km = [i * 1000.0 for i in range(30)]
    health = [100.0 - 0.001 * i for i in range(30)]
    result = estimate_rul(history(km, health), 100_000, avg_km_per_day=100)
    assert result.rul_days <= MAX_RUL_DAYS


def test_curve_separates_observed_from_projected():
    km = [i * 1000.0 for i in range(30)]
    health = [100.0 - i for i in range(30)]
    result = estimate_rul(history(km, health), 100_000, 100)

    observed = [p for p in result.curve if not p["projected"]]
    projected = [p for p in result.curve if p["projected"]]
    # 30 weeks supplied, but only the fitting window is charted as observed.
    assert len(observed) == 26
    assert projected, "a declining part should have a projected tail"
    # The projection ends at the failure threshold, not below it.
    assert projected[-1]["health_index"] == pytest.approx(FAILURE_THRESHOLD_INDEX, abs=1.0)
    assert projected[0]["km_on_part"] > observed[-1]["km_on_part"]


def test_only_the_last_26_weeks_are_fitted():
    """An old, steep decline must not drag a recently stabilised part down."""
    km = [i * 1000.0 for i in range(60)]
    health = [100.0 - 3 * i for i in range(30)] + [10.0 - 0.01 * i for i in range(30)]
    result = estimate_rul(history(km, health), 100_000, 100, fit_weeks=26)
    assert len(result.curve) - len([p for p in result.curve if p["projected"]]) == 26
