"""Cost impact - spec 6.8."""

from __future__ import annotations

import pytest

from app.constants import (
    DOWNTIME_COST_PER_HOUR,
    PLANNED_DOWNTIME_FACTOR,
    TOW_COST,
    WORKSHOP_HOURLY_RATE,
)
from app.services.cost import estimate_cost_impact


def test_unplanned_always_costs_more_than_planned():
    impact = estimate_cost_impact(unit_cost=18_500, labour_hours=3.5, failure_probability=1.0)
    assert impact.unplanned_cost > impact.planned_cost


def test_the_gap_is_the_tow_plus_the_extra_downtime():
    downtime = 10.0
    impact = estimate_cost_impact(
        unit_cost=10_000, labour_hours=2.0, failure_probability=1.0, downtime_hours=downtime
    )
    expected_gap = TOW_COST + downtime * (1 - PLANNED_DOWNTIME_FACTOR) * DOWNTIME_COST_PER_HOUR
    assert impact.avoidable_cost == pytest.approx(expected_gap, rel=1e-6)


def test_planned_cost_covers_parts_and_labour():
    impact = estimate_cost_impact(
        unit_cost=10_000, labour_hours=2.0, failure_probability=0.5, downtime_hours=0.0
    )
    assert impact.planned_cost == pytest.approx(10_000 + 2.0 * WORKSHOP_HOURLY_RATE)


def test_exposure_is_the_avoidable_cost_weighted_by_probability():
    impact = estimate_cost_impact(
        unit_cost=10_000, labour_hours=2.0, failure_probability=0.25, downtime_hours=8.0
    )
    assert impact.estimated_cost_impact == pytest.approx(impact.avoidable_cost * 0.25, rel=1e-6)


def test_zero_probability_carries_no_exposure():
    impact = estimate_cost_impact(20_000, 4.0, failure_probability=0.0)
    assert impact.estimated_cost_impact == 0.0
    # The underlying cost gap still exists; only the expectation is zero.
    assert impact.avoidable_cost > 0


def test_downtime_defaults_to_a_multiple_of_labour_when_no_history_exists():
    with_default = estimate_cost_impact(10_000, 4.0, 1.0)
    with_explicit = estimate_cost_impact(10_000, 4.0, 1.0, downtime_hours=12.0)
    assert with_default.unplanned_cost == pytest.approx(with_explicit.unplanned_cost)


def test_a_more_expensive_part_carries_more_exposure_only_through_its_downtime():
    """Part cost cancels out of the gap - it is paid either way."""
    cheap = estimate_cost_impact(1_000, 2.0, 1.0, downtime_hours=6.0)
    dear = estimate_cost_impact(90_000, 2.0, 1.0, downtime_hours=6.0)
    assert cheap.avoidable_cost == pytest.approx(dear.avoidable_cost)
    assert dear.unplanned_cost > cheap.unplanned_cost
