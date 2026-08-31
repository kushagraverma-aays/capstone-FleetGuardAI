"""Back-test metrics and alert-episode collapsing - spec 6.4."""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.backtest import backtest_rule, collapse_to_episodes


def days(*offsets: int) -> list[pd.Timestamp]:
    base = pd.Timestamp("2025-01-06")
    return [base + pd.Timedelta(days=o) for o in offsets]


# --- episode collapsing -------------------------------------------------------


def test_no_alerts_makes_no_episodes():
    assert collapse_to_episodes([], 45) == []


def test_a_weekly_run_collapses_to_one_episode():
    """The whole point: sixty weekly alerts are one warning, not sixty."""
    weekly = days(*range(0, 120, 7))
    episodes = collapse_to_episodes(weekly, 45)
    assert len(episodes) == 1
    assert episodes[0] == (weekly[0], weekly[-1])


def test_a_gap_longer_than_the_window_opens_a_new_episode():
    episodes = collapse_to_episodes(days(0, 7, 14, 100, 107), 45)
    assert len(episodes) == 2
    assert episodes[0] == tuple(days(0, 14))
    assert episodes[1] == tuple(days(100, 107))


def test_a_gap_exactly_at_the_window_stays_one_episode():
    episodes = collapse_to_episodes(days(0, 45), 45)
    assert len(episodes) == 1


def test_a_gap_one_day_past_the_window_splits():
    episodes = collapse_to_episodes(days(0, 46), 45)
    assert len(episodes) == 2


def test_episodes_are_returned_in_order_regardless_of_input_order():
    episodes = collapse_to_episodes(days(100, 0, 107, 7), 45)
    assert episodes[0][0] < episodes[1][0]


# --- metrics ------------------------------------------------------------------


def build_features(vin_scores: dict[str, list[float]]) -> pd.DataFrame:
    """One synthetic component, weekly rows, probability driven by one signal.

    age_fraction is held at zero so the probability is exactly 0.30*signal
    scaled - the test sets the signal to hit the thresholds it wants.
    """
    rows = []
    for vin, scores in vin_scores.items():
        for week, score in enumerate(scores):
            rows.append(
                {
                    "vin": vin,
                    "part_code": "TST-0001",
                    "week_start_date": pd.Timestamp("2025-01-06")
                    + pd.Timedelta(weeks=week),
                    "age_fraction": score,
                    "signal": 0.0,
                }
            )
    return pd.DataFrame(rows)


WEIGHTS = {"signal": 1.0}


def test_a_rule_that_never_alerts_scores_zero_precision_and_coverage():
    features = build_features({"VIN1": [0.1] * 20})
    failures = pd.DataFrame(columns=["vin", "part_code", "event_date"])
    result = backtest_rule(features, failures, WEIGHTS)
    assert result.alert_episodes == 0
    assert result.precision == 0.0
    assert result.coverage == 0.0


def test_an_alert_followed_by_a_failure_is_a_true_positive():
    # age_fraction 1.0 -> probability 0.70, exactly the RED threshold.
    features = build_features({"VIN1": [1.0] * 10})
    failures = pd.DataFrame(
        {
            "vin": ["VIN1"],
            "part_code": ["TST-0001"],
            "event_date": [pd.Timestamp("2025-02-10")],
        }
    )
    result = backtest_rule(features, failures, WEIGHTS)
    assert result.alert_episodes == 1
    assert result.true_positive_episodes == 1
    assert result.precision == pytest.approx(1.0)
    assert result.coverage == pytest.approx(1.0)
    assert result.sample_failures == 1


def test_an_alert_with_no_failure_is_a_false_positive():
    features = build_features({"VIN1": [1.0] * 10})
    failures = pd.DataFrame(columns=["vin", "part_code", "event_date"])
    result = backtest_rule(features, failures, WEIGHTS)
    assert result.alert_episodes == 1
    assert result.true_positive_episodes == 0
    assert result.precision == 0.0


def test_a_failure_with_no_alert_hurts_coverage_but_not_precision():
    features = build_features({"VIN1": [0.1] * 10})
    failures = pd.DataFrame(
        {
            "vin": ["VIN1"],
            "part_code": ["TST-0001"],
            "event_date": [pd.Timestamp("2025-02-10")],
        }
    )
    result = backtest_rule(features, failures, WEIGHTS)
    assert result.coverage == 0.0
    assert result.caught_failures == 0
    assert result.sample_failures == 1


def test_precision_and_coverage_across_two_vehicles():
    # VIN1 alerts and fails; VIN2 alerts and does not.
    features = build_features({"VIN1": [1.0] * 10, "VIN2": [1.0] * 10})
    failures = pd.DataFrame(
        {
            "vin": ["VIN1"],
            "part_code": ["TST-0001"],
            "event_date": [pd.Timestamp("2025-02-10")],
        }
    )
    result = backtest_rule(features, failures, WEIGHTS)
    assert result.alert_episodes == 2
    assert result.true_positive_episodes == 1
    assert result.precision == pytest.approx(0.5)
    assert result.coverage == pytest.approx(1.0)


def test_lead_time_measures_from_the_first_alert_inside_the_horizon():
    features = build_features({"VIN1": [1.0] * 6})
    failure_date = pd.Timestamp("2025-01-06") + pd.Timedelta(weeks=5)
    failures = pd.DataFrame(
        {"vin": ["VIN1"], "part_code": ["TST-0001"], "event_date": [failure_date]}
    )
    result = backtest_rule(features, failures, WEIGHTS)
    # First alert is week 0, failure is week 5 -> 35 days of warning.
    assert result.days_to_alert == pytest.approx(35.0)


def test_empty_inputs_are_handled_without_dividing_by_zero():
    empty = pd.DataFrame(columns=["vin", "part_code", "week_start_date", "age_fraction"])
    failures = pd.DataFrame(columns=["vin", "part_code", "event_date"])
    result = backtest_rule(empty, failures, WEIGHTS)
    assert result.precision == 0.0
    assert result.coverage == 0.0


def test_a_rule_with_no_weights_raises_no_alerts():
    features = build_features({"VIN1": [1.0] * 10})
    failures = pd.DataFrame(columns=["vin", "part_code", "event_date"])
    assert backtest_rule(features, failures, {}).alert_episodes == 0
