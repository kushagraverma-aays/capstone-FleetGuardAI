"""Cost impact (spec section 6.8).

Every screen should be able to express risk in currency, not just percentages
- that is what makes the difference between an interesting chart and a
purchase order.

Two costs are compared for the same replacement:

  unplanned  part + labour + downtime + a highway recovery
  planned    part + labour + a fraction of the downtime, no tow

The difference is what acting early actually saves. `estimated_cost_impact`
weights that saving by the failure probability, so summing the column across a
fleet gives an expected exposure rather than a worst case that will never all
happen at once.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.constants import (
    DOWNTIME_COST_PER_HOUR,
    PLANNED_DOWNTIME_FACTOR,
    TOW_COST,
    WORKSHOP_HOURLY_RATE,
)

# Roadside failures take far longer to resolve than a booked workshop slot:
# diagnosis, parts that are not on the shelf, and a driver waiting.
UNPLANNED_DOWNTIME_MULTIPLIER = 3.0


@dataclass(frozen=True)
class CostImpact:
    unplanned_cost: float
    planned_cost: float
    avoidable_cost: float
    estimated_cost_impact: float

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_cost_impact(
    unit_cost: float,
    labour_hours: float,
    failure_probability: float,
    downtime_hours: float | None = None,
) -> CostImpact:
    """Cost of this component failing unplanned versus being replaced on plan.

    `downtime_hours` should be the observed median for the component where
    history exists; without it, labour hours scaled by the roadside multiplier
    is a reasonable stand-in.
    """
    unit_cost = float(unit_cost)
    labour_hours = float(labour_hours)
    if downtime_hours is None:
        downtime_hours = labour_hours * UNPLANNED_DOWNTIME_MULTIPLIER

    labour_cost = labour_hours * WORKSHOP_HOURLY_RATE

    unplanned = (
        unit_cost + labour_cost + downtime_hours * DOWNTIME_COST_PER_HOUR + TOW_COST
    )
    planned = (
        unit_cost
        + labour_cost
        + downtime_hours * PLANNED_DOWNTIME_FACTOR * DOWNTIME_COST_PER_HOUR
    )
    avoidable = max(0.0, unplanned - planned)

    return CostImpact(
        unplanned_cost=round(unplanned, 2),
        planned_cost=round(planned, 2),
        avoidable_cost=round(avoidable, 2),
        estimated_cost_impact=round(avoidable * float(failure_probability), 2),
    )
