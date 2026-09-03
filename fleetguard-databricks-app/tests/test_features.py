"""Feature table construction - spec 6.1."""

from __future__ import annotations

import pandas as pd
import pytest

from app.constants import LABEL_HORIZON_DAYS, ROLLING_WEEKS, SIGNALS
from app.services.features import _attach_km_on_part, _attach_label, smooth_signals


def weeks(n: int) -> list[pd.Timestamp]:
    return [pd.Timestamp("2025-01-06") + pd.Timedelta(weeks=i) for i in range(n)]


def features_frame(n: int = 10, vin: str = "VIN1") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "vin": vin,
            "part_code": "TST-0001",
            "week_start_date": weeks(n),
            "odometer_km": [10_000 + i * 1_000 for i in range(n)],
        }
    )


# --- smoothing ----------------------------------------------------------------


def test_rolling_mean_smooths_a_spike():
    frame = pd.DataFrame({"vin": ["V1"] * 5, "week_start_date": weeks(5)})
    for signal in SIGNALS:
        frame[signal] = [0.0, 0.0, 1.0, 0.0, 0.0]

    smoothed = smooth_signals(frame)
    # The spike is averaged over the 4-week window rather than left standing.
    assert smoothed["coolant_temp_variance"].iloc[2] == pytest.approx(1 / 3)
    assert smoothed["coolant_temp_variance"].max() < 1.0


def test_smoothing_does_not_bleed_across_vehicles():
    frame = pd.DataFrame(
        {"vin": ["V1", "V1", "V2", "V2"], "week_start_date": weeks(2) + weeks(2)}
    )
    for signal in SIGNALS:
        frame[signal] = [1.0, 1.0, 0.0, 0.0]

    smoothed = smooth_signals(frame)
    v2 = smoothed[smoothed["vin"] == "V2"]["coolant_temp_variance"]
    assert (v2 == 0.0).all()


def test_the_first_weeks_are_kept_rather_than_dropped():
    frame = pd.DataFrame({"vin": ["V1"] * 3, "week_start_date": weeks(3)})
    for signal in SIGNALS:
        frame[signal] = [0.4, 0.6, 0.8]
    smoothed = smooth_signals(frame)
    assert len(smoothed) == 3
    assert smoothed["coolant_temp_variance"].iloc[0] == pytest.approx(0.4)
    assert ROLLING_WEEKS == 4


# --- km on part ---------------------------------------------------------------


def test_km_on_part_counts_from_the_fitment_odometer():
    features = features_frame(3)
    job_cards = pd.DataFrame(
        {
            "vin": ["VIN1"],
            "part_code": ["TST-0001"],
            "event_date": [pd.Timestamp("2024-12-01")],
            "odometer_reading": [8_000],
            "event_type": ["fitment"],
        }
    )
    result = _attach_km_on_part(features, job_cards)
    assert result["km_on_part"].tolist() == [2_000, 3_000, 4_000]


def test_a_replacement_resets_the_part_clock():
    """A failure installs a new part, so km_on_part must start again."""
    features = features_frame(4)
    job_cards = pd.DataFrame(
        {
            "vin": ["VIN1", "VIN1"],
            "part_code": ["TST-0001", "TST-0001"],
            "event_date": [pd.Timestamp("2024-12-01"), pd.Timestamp("2025-01-15")],
            "odometer_reading": [8_000, 11_500],
            "event_type": ["fitment", "failure"],
        }
    )
    result = _attach_km_on_part(features, job_cards).sort_values("week_start_date")
    # Weeks 0 and 1 predate the replacement; weeks 2 and 3 follow it.
    assert result["km_on_part"].tolist() == [2_000, 3_000, 500, 1_500]


def test_a_preventive_swap_also_resets_the_clock():
    features = features_frame(3)
    job_cards = pd.DataFrame(
        {
            "vin": ["VIN1", "VIN1"],
            "part_code": ["TST-0001", "TST-0001"],
            "event_date": [pd.Timestamp("2024-12-01"), pd.Timestamp("2025-01-10")],
            "odometer_reading": [8_000, 11_000],
            "event_type": ["fitment", "preventive"],
        }
    )
    result = _attach_km_on_part(features, job_cards).sort_values("week_start_date")
    # The swap on the 10th lands before week 1 (the 13th), so the part reads
    # zero km that week and starts accumulating again from there.
    assert result["km_on_part"].tolist() == [2_000, 0, 1_000]


def test_km_on_part_never_goes_negative():
    features = features_frame(1)
    job_cards = pd.DataFrame(
        {
            "vin": ["VIN1"],
            "part_code": ["TST-0001"],
            "event_date": [pd.Timestamp("2024-12-01")],
            "odometer_reading": [50_000],
            "event_type": ["fitment"],
        }
    )
    assert _attach_km_on_part(features, job_cards)["km_on_part"].iloc[0] == 0


# --- labelling ----------------------------------------------------------------


def test_a_failure_inside_the_horizon_labels_the_week():
    features = features_frame(2)
    job_cards = pd.DataFrame(
        {
            "vin": ["VIN1"],
            "part_code": ["TST-0001"],
            "event_date": [pd.Timestamp("2025-02-03")],
            "odometer_reading": [12_000],
            "event_type": ["failure"],
        }
    )
    result = _attach_label(features, job_cards)
    assert result["failed_within_horizon"].tolist() == [1, 1]


def test_a_failure_beyond_the_horizon_does_not_label_the_week():
    features = features_frame(1)
    far = pd.Timestamp("2025-01-06") + pd.Timedelta(days=LABEL_HORIZON_DAYS + 5)
    job_cards = pd.DataFrame(
        {
            "vin": ["VIN1"],
            "part_code": ["TST-0001"],
            "event_date": [far],
            "odometer_reading": [12_000],
            "event_type": ["failure"],
        }
    )
    result = _attach_label(features, job_cards)
    assert result["failed_within_horizon"].tolist() == [0]


def test_preventive_and_fitment_events_are_never_labels():
    """Labelling planned work as failure teaches the model that good
    maintenance is a fault."""
    features = features_frame(2)
    job_cards = pd.DataFrame(
        {
            "vin": ["VIN1", "VIN1"],
            "part_code": ["TST-0001", "TST-0001"],
            "event_date": [pd.Timestamp("2025-01-10"), pd.Timestamp("2025-01-12")],
            "odometer_reading": [11_000, 11_200],
            "event_type": ["preventive", "fitment"],
        }
    )
    result = _attach_label(features, job_cards)
    assert result["failed_within_horizon"].tolist() == [0, 0]


def test_no_failures_at_all_labels_everything_zero():
    features = features_frame(3)
    job_cards = pd.DataFrame(
        columns=["vin", "part_code", "event_date", "odometer_reading", "event_type"]
    )
    result = _attach_label(features, job_cards)
    assert result["failed_within_horizon"].tolist() == [0, 0, 0]
