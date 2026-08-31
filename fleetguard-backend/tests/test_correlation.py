"""Signal ranking - spec 6.2."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.constants import SIGNALS
from app.services.correlation import rank_signals, top_signals


def build_features(n: int = 400, seed: int = 7) -> pd.DataFrame:
    """A frame where one signal drives the label and one opposes it."""
    rng = np.random.default_rng(seed)
    labels = np.array([1] * (n // 2) + [0] * (n // 2))

    frame = pd.DataFrame({signal: rng.uniform(0, 1, n) for signal in SIGNALS})
    # Driver: clearly higher when the part failed.
    frame["coolant_temp_variance"] = np.where(
        labels == 1, rng.uniform(0.6, 1.0, n), rng.uniform(0.0, 0.4, n)
    )
    # Protective: clearly lower when the part failed.
    frame["idle_time_pct"] = np.where(
        labels == 1, rng.uniform(0.0, 0.3, n), rng.uniform(0.7, 1.0, n)
    )
    frame["failed_within_horizon"] = labels
    return frame


def test_the_driving_signal_ranks_first():
    ranked = rank_signals(build_features())
    assert ranked[0].signal == "coolant_temp_variance"
    assert ranked[0].correlation > 0.5


def test_results_are_sorted_by_correlation_descending():
    ranked = rank_signals(build_features())
    values = [r.correlation for r in ranked]
    assert values == sorted(values, reverse=True)


def test_every_signal_is_reported_even_when_uncorrelated():
    ranked = rank_signals(build_features())
    assert {r.signal for r in ranked} == set(SIGNALS)


def test_negative_correlation_is_floored_at_zero():
    """A signal that protects against failure is not a risk input."""
    ranked = {r.signal: r for r in rank_signals(build_features())}
    protective = ranked["idle_time_pct"]
    assert protective.raw_correlation < 0
    assert protective.correlation == 0.0


def test_means_are_reported_for_both_classes():
    ranked = {r.signal: r for r in rank_signals(build_features())}
    driver = ranked["coolant_temp_variance"]
    assert driver.mean_when_failed > driver.mean_when_healthy


def test_logistic_cross_check_is_populated():
    ranked = {r.signal: r for r in rank_signals(build_features())}
    assert ranked["coolant_temp_variance"].logit_coefficient > 0


def test_a_single_class_cannot_be_correlated():
    frame = build_features()
    frame["failed_within_horizon"] = 0
    assert rank_signals(frame) == []


def test_an_empty_frame_returns_nothing():
    assert rank_signals(pd.DataFrame()) == []


def test_a_constant_signal_scores_zero_rather_than_nan():
    frame = build_features()
    frame["battery_voltage_sag"] = 0.5
    ranked = {r.signal: r for r in rank_signals(frame)}
    assert ranked["battery_voltage_sag"].correlation == 0.0
    assert not np.isnan(ranked["battery_voltage_sag"].p_value)


def test_top_signals_respects_the_limit_and_the_floor():
    ranked = rank_signals(build_features())
    assert len(top_signals(ranked, limit=3)) == 3
    assert all(r.correlation >= 0.2 for r in top_signals(ranked, 9, minimum=0.2))


def test_labels_are_read_from_the_expected_column():
    frame = build_features().drop(columns=["failed_within_horizon"])
    assert rank_signals(frame) == []


def test_correlation_is_reproducible_for_the_same_input():
    first = rank_signals(build_features(seed=3))
    second = rank_signals(build_features(seed=3))
    assert [r.correlation for r in first] == pytest.approx([r.correlation for r in second])
