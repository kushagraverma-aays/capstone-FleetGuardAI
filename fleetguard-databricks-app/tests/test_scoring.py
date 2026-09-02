"""Health index, probability and risk tiers - spec 6.5 and 6.7."""

from __future__ import annotations

import pandas as pd
import pytest

from app.constants import AMBER_THRESHOLD, RED_THRESHOLD, URGENT_RUL_DAYS
from app.services import scoring


def test_health_index_is_100_for_a_new_unstressed_part():
    assert scoring.health_index(age_fraction=0.0, stress=0.0) == 100.0


def test_health_index_applies_the_70_30_split():
    # 100 - 70*0.5 - 30*0.5 = 50
    assert scoring.health_index(0.5, 0.5) == pytest.approx(50.0)


def test_health_index_clamps_to_zero_rather_than_going_negative():
    assert scoring.health_index(age_fraction=1.5, stress=1.0) == 0.0


def test_health_index_clamps_at_100():
    assert scoring.health_index(age_fraction=-0.2, stress=0.0) == 100.0


def test_probability_is_the_complement_of_health():
    assert scoring.failure_probability(75.0) == pytest.approx(0.25)
    assert scoring.failure_probability(0.0) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("probability", "expected"),
    [
        (0.0, "GREEN"),
        (AMBER_THRESHOLD - 0.001, "GREEN"),
        (AMBER_THRESHOLD, "AMBER"),
        (RED_THRESHOLD - 0.001, "AMBER"),
        (RED_THRESHOLD, "RED"),
        (1.0, "RED"),
    ],
)
def test_risk_tier_boundaries(probability, expected):
    assert scoring.risk_tier(probability) == expected


def test_short_rul_escalates_a_green_component_to_red():
    # Low age and low stress would read GREEN on probability alone.
    result = scoring.assess(age_fraction=0.1, stress=0.1, rul_days=3)
    assert result.risk_tier == "RED"
    assert result.escalated is True
    assert "3 days" in result.escalation_reason


def test_escalation_does_not_fire_beyond_the_urgency_window():
    result = scoring.assess(age_fraction=0.1, stress=0.1, rul_days=URGENT_RUL_DAYS + 1)
    assert result.risk_tier == "GREEN"
    assert result.escalated is False
    assert result.escalation_reason is None


def test_an_already_red_component_is_not_marked_escalated():
    result = scoring.assess(age_fraction=1.0, stress=1.0, rul_days=1)
    assert result.risk_tier == "RED"
    assert result.escalated is False


def test_missing_rul_never_escalates():
    result = scoring.assess(age_fraction=0.1, stress=0.1, rul_days=None)
    assert result.risk_tier == "GREEN"


def test_stress_is_the_weighted_signal_sum():
    signals = {"a": 0.5, "b": 1.0, "c": 0.2}
    weights = {"a": 0.5, "b": 0.5}
    # c is not in the rule and must be ignored entirely.
    assert scoring.stress_from_weights(signals, weights) == pytest.approx(0.75)


def test_vectorised_probability_agrees_with_the_scalar_path():
    """The back-test and the scoring CLI must not disagree with assess()."""
    frame = pd.DataFrame(
        {
            "age_fraction": [0.0, 0.25, 0.5, 0.9],
            "sig_a": [0.0, 0.4, 0.6, 1.0],
            "sig_b": [0.2, 0.4, 0.8, 1.0],
        }
    )
    weights = {"sig_a": 0.6, "sig_b": 0.4}

    vectorised = scoring.probability_frame(frame, weights)

    for i, row in frame.iterrows():
        stress = scoring.stress_from_weights(
            {"sig_a": row["sig_a"], "sig_b": row["sig_b"]}, weights
        )
        scalar = scoring.assess(row["age_fraction"], stress, rul_days=None)
        assert vectorised.iloc[i] == pytest.approx(scalar.failure_probability, abs=1e-9)


def test_stress_frame_ignores_signals_outside_the_rule():
    frame = pd.DataFrame({"sig_a": [1.0], "sig_b": [1.0], "age_fraction": [0.0]})
    assert scoring.stress_frame(frame, {"sig_a": 1.0}).iloc[0] == pytest.approx(1.0)


def test_cross_check_sentence_quotes_both_views():
    sentence = scoring.cross_check_sentence(0.82, "RED", 12.0, 4200.0, "Alternator")
    assert "82%" in sentence
    assert "RED" in sentence
    assert "4,200" in sentence
    assert "12" in sentence
