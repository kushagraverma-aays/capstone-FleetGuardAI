"""Weight normalisation and formula rendering - spec 6.3."""

from __future__ import annotations

import pytest

from app.services.correlation import SignalCorrelation
from app.services.rules_engine import (
    default_selection,
    describe_weights,
    format_formula,
    normalise_weights,
)


def correlation(signal: str, value: float) -> SignalCorrelation:
    return SignalCorrelation(
        signal=signal,
        label=signal.replace("_", " ").title(),
        correlation=value,
        raw_correlation=value,
        p_value=0.0,
        logit_coefficient=0.0,
        mean_when_failed=0.0,
        mean_when_healthy=0.0,
    )


CORRELATIONS = [
    correlation("coolant_temp_variance", 0.40),
    correlation("overload_duty_share", 0.30),
    correlation("oil_pressure_dips", 0.20),
    correlation("idle_time_pct", 0.10),
    correlation("short_trip_ratio", 0.0),
]


def test_weights_sum_to_exactly_one():
    weights = normalise_weights(CORRELATIONS, [c.signal for c in CORRELATIONS[:4]])
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)


def test_weights_are_proportional_to_correlation():
    weights = normalise_weights(CORRELATIONS, ["coolant_temp_variance", "overload_duty_share"])
    # 0.40 and 0.30 of a 0.70 total.
    assert weights["coolant_temp_variance"] == pytest.approx(0.5714, abs=1e-4)
    assert weights["overload_duty_share"] == pytest.approx(0.4286, abs=1e-4)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize(
    "selection",
    [
        ["coolant_temp_variance"],
        ["coolant_temp_variance", "overload_duty_share"],
        ["coolant_temp_variance", "overload_duty_share", "oil_pressure_dips"],
        ["coolant_temp_variance", "overload_duty_share", "oil_pressure_dips", "idle_time_pct"],
    ],
)
def test_weights_always_renormalise_to_one_as_signals_are_toggled(selection):
    """Toggling signals in Rule Studio must always land back on 1.00."""
    weights = normalise_weights(CORRELATIONS, selection)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert set(weights) == set(selection)


def test_a_single_signal_takes_the_whole_weight():
    weights = normalise_weights(CORRELATIONS, ["coolant_temp_variance"])
    assert weights == {"coolant_temp_variance": 1.0}


def test_zero_correlation_signals_are_dropped():
    weights = normalise_weights(CORRELATIONS, ["coolant_temp_variance", "short_trip_ratio"])
    assert "short_trip_ratio" not in weights
    assert weights["coolant_temp_variance"] == pytest.approx(1.0)


def test_selecting_nothing_usable_yields_no_weights():
    assert normalise_weights(CORRELATIONS, []) == {}
    assert normalise_weights(CORRELATIONS, ["short_trip_ratio"]) == {}


def test_weights_are_ordered_heaviest_first():
    weights = normalise_weights(CORRELATIONS, [c.signal for c in CORRELATIONS[:4]])
    assert list(weights.values()) == sorted(weights.values(), reverse=True)


def test_formula_reads_like_the_spec_example():
    weights = normalise_weights(CORRELATIONS, ["coolant_temp_variance", "overload_duty_share"])
    formula = format_formula(weights)
    assert formula.startswith("failure_probability = ")
    assert "coolant_temp_variance" in formula
    assert " + " in formula


def test_formula_handles_an_empty_rule():
    assert format_formula({}) == "failure_probability = 0"


def test_default_selection_takes_the_strongest_signals_above_the_floor():
    selected = default_selection(CORRELATIONS)
    assert selected[0] == "coolant_temp_variance"
    # short_trip_ratio sits at 0.0, below MIN_CORRELATION.
    assert "short_trip_ratio" not in selected


def test_describe_weights_reports_shares_that_total_100():
    weights = normalise_weights(CORRELATIONS, [c.signal for c in CORRELATIONS[:3]])
    described = describe_weights(weights, CORRELATIONS)
    assert sum(d["share"] for d in described) == pytest.approx(100.0, abs=0.2)
    assert all(d["label"] for d in described)
