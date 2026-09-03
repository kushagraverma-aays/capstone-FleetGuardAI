"""Domain constants for the FleetGuard analytics engine.

These are modelling decisions, not deployment configuration, so they live in
code rather than in environment variables. Every threshold here is referenced
by the specification in docs/SPECS.md; the section is noted alongside each.
"""

from __future__ import annotations

# --- Telematics signals ------------------------------------------------------
# The nine normalised (0-1) weekly signals carried on telematics_weekly.
SIGNALS: list[str] = [
    "coolant_temp_variance",
    "oil_pressure_dips",
    "battery_voltage_sag",
    "dtc_recurrence_rate",
    "harsh_braking_frequency",
    "overload_duty_share",
    "high_rpm_dwell_time",
    "short_trip_ratio",
    "idle_time_pct",
]

SIGNAL_LABELS: dict[str, str] = {
    "coolant_temp_variance": "Coolant temp variance",
    "oil_pressure_dips": "Oil pressure dips",
    "battery_voltage_sag": "Battery voltage sag",
    "dtc_recurrence_rate": "DTC recurrence rate",
    "harsh_braking_frequency": "Harsh braking frequency",
    "overload_duty_share": "Overload duty share",
    "high_rpm_dwell_time": "High-RPM dwell time",
    "short_trip_ratio": "Short-trip ratio",
    "idle_time_pct": "Idle time %",
}

# --- Feature table (spec 6.1) ------------------------------------------------
# 90 days, not 30: at a 30-day horizon the base failure rate sits under 1%,
# which makes any resulting probability meaningless. 90 days also matches part
# lead time plus workshop scheduling.
LABEL_HORIZON_DAYS = 90
ROLLING_WEEKS = 4

# --- Correlation / rule builder (spec 6.2, 6.3) ------------------------------
MIN_CORRELATION = 0.05
DEFAULT_TOP_N_SIGNALS = 5

# --- Back-testing (spec 6.4) -------------------------------------------------
BACKTEST_LOOKBACK_DAYS = 365
# Consecutive alerts inside this window collapse into one alert episode,
# otherwise precision is inflated by counting the same warning every week.
BACKTEST_EPISODE_DAYS = 45

# --- Health index (spec 6.5) -------------------------------------------------
# health_index = 100 - 70*age_fraction - 30*stress, clamped to 0-100.
# failure_probability = 1 - health_index/100.
WEIGHT_AGE = 70.0
WEIGHT_STRESS = 30.0
FAILURE_THRESHOLD_INDEX = 30.0

# --- RUL (spec 6.6) ----------------------------------------------------------
RUL_FIT_WEEKS = 26
TREND_WEEKS = 10

# --- Risk tiers (spec 6.7) ---------------------------------------------------
AMBER_THRESHOLD = 0.40
RED_THRESHOLD = 0.70
URGENT_RUL_DAYS = 7

# --- Cost impact (spec 6.8) --------------------------------------------------
WORKSHOP_HOURLY_RATE = 850.0     # currency units per labour hour
TOW_COST = 18_000.0              # highway recovery of a laden commercial vehicle
DOWNTIME_COST_PER_HOUR = 2_400.0 # lost revenue while the vehicle is off the road
# A planned replacement still costs parts and labour, but no tow and far less
# downtime; this is the share of downtime hours retained when work is scheduled.
PLANNED_DOWNTIME_FACTOR = 0.35

# --- Roles (spec 3) ----------------------------------------------------------
ROLE_MANUFACTURER_ADMIN = "manufacturer_admin"
ROLE_CUSTOMER_ADMIN = "customer_admin"
ROLE_VIEWER = "viewer"
ROLES = [ROLE_MANUFACTURER_ADMIN, ROLE_CUSTOMER_ADMIN, ROLE_VIEWER]
