"""Response models for customers, parts, vehicles, predictions and RUL."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from app.schemas.common import ApiModel


# --- auth --------------------------------------------------------------------


class LoginRequest(ApiModel):
    email: str = Field(description="Demo logins are seeded by the data generator.")
    password: str


class TokenResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    role: str
    customer_id: int | None
    full_name: str
    email: str


# --- customers ---------------------------------------------------------------


class CustomerOut(ApiModel):
    customer_id: int
    name: str
    region: str
    contact_email: str
    contract_tier: str
    vehicle_count: int = 0
    red_count: int = 0
    cost_exposure: float = 0.0


# --- parts -------------------------------------------------------------------


class PartOut(ApiModel):
    part_code: str
    part_name: str
    category: str
    design_life_km: int
    unit_cost: float
    lead_time_days: int
    labour_hours: float
    tracked_vehicles: int = 0
    failures_12m: int = 0
    red_count: int = 0
    has_active_rule: bool = False
    rule_precision: float | None = None
    rule_coverage: float | None = None
    rule_days_to_alert: float | None = None


class PartHistoryPoint(ApiModel):
    month: str = Field(description="First day of the month, ISO format.")
    failures: int
    preventive: int


class PartHistory(ApiModel):
    part_code: str
    part_name: str
    design_life_km: int
    total_failures: int
    total_preventive: int
    median_km_at_failure: float
    median_life_used_pct: float = Field(
        description="Median km-on-part at failure as a percentage of design life."
    )
    mean_downtime_hours: float
    warranty_claims: int
    warranty_amount: float
    monthly: list[PartHistoryPoint]


class SignalCorrelationOut(ApiModel):
    signal: str
    label: str
    correlation: float
    raw_correlation: float
    p_value: float
    logit_coefficient: float
    mean_when_failed: float
    mean_when_healthy: float


class PartCorrelations(ApiModel):
    part_code: str
    part_name: str
    sample_rows: int
    sample_failures: int
    correlations: list[SignalCorrelationOut]
    suggested_signals: list[str] = Field(
        description="The signals the Rule Studio pre-selects: strongest above the floor."
    )


# --- rules -------------------------------------------------------------------


class RuleSignalOut(ApiModel):
    signal: str
    label: str
    correlation: float
    weight: float
    share: float
    included: bool


class BacktestMetrics(ApiModel):
    precision: float
    coverage: float
    days_to_alert: float
    sample_failures: int
    alert_episodes: int
    true_positive_episodes: int
    caught_failures: int
    alert_threshold: float
    censored_episodes: int = Field(
        default=0,
        description=(
            "Alert episodes whose 90-day outcome window runs past the end of "
            "the data. Excluded from precision because their outcome cannot "
            "be observed yet, not because they were wrong."
        ),
    )


class RuleOut(ApiModel):
    rule_id: int
    part_code: str
    part_name: str
    version: int
    formula: str
    precision: float
    coverage: float
    days_to_alert: float
    sample_failures: int
    is_active: bool
    created_by: str
    created_at: datetime
    signals: list[RuleSignalOut]


class RulePreviewRequest(ApiModel):
    part_code: str
    signals: list[str] | None = Field(
        default=None,
        description=(
            "Signals to include. Omit to use the default selection: the "
            "strongest signals clearing the correlation floor."
        ),
    )


class RulePreview(ApiModel):
    part_code: str
    part_name: str
    formula: str
    selected_signals: list[str]
    weights: list[RuleSignalOut]
    correlations: list[SignalCorrelationOut]
    metrics: BacktestMetrics
    weight_total: float = Field(description="Always 1.00 for a non-empty rule.")


class RuleDeployRequest(RulePreviewRequest):
    note: str | None = Field(
        default=None, description="Free text recorded on the audit entry."
    )


# --- predictions -------------------------------------------------------------


class PredictionOut(ApiModel):
    vin: str
    part_code: str
    part_name: str
    customer_id: int
    customer_name: str
    model: str
    variant: str
    region: str
    failure_probability: float
    risk_tier: str
    health_index: float
    rul_km: float
    rul_days: float
    window_from_days: int
    window_to_days: int
    model_confidence: float
    degradation_trend: float
    top_signal: str | None
    top_signal_share: float
    escalated: bool
    escalation_reason: str | None
    estimated_cost_impact: float
    computed_date: date


class DriverOut(ApiModel):
    signal: str
    label: str
    value: float
    weight: float
    contribution: float
    share: float


class TrendPoint(ApiModel):
    week: str
    probability: float
    health_index: float


class CurvePoint(ApiModel):
    km_on_part: float
    health_index: float
    projected: bool


class CostBreakdown(ApiModel):
    unplanned_cost: float
    planned_cost: float
    avoidable_cost: float
    estimated_cost_impact: float


class PredictionDetail(PredictionOut):
    drivers: list[DriverOut]
    trend: list[TrendPoint]
    curve: list[CurvePoint]
    cost: CostBreakdown
    rule: RuleOut | None
    cross_check: str = Field(
        description="States the probability and the RUL together so the two views can be seen to agree."
    )
    km_on_part: float
    design_life_km: int
    life_used_pct: float
    lead_time_days: int


# --- vehicles ----------------------------------------------------------------


class VehicleOut(ApiModel):
    vin: str
    customer_id: int
    customer_name: str
    model: str
    variant: str
    region: str
    registration_date: date
    total_km_driven: int
    avg_km_per_day: float
    status: str
    worst_part_code: str | None = None
    worst_part_name: str | None = None
    worst_probability: float = 0.0
    risk_tier: str = "GREEN"
    min_rul_days: float = 0.0
    red_count: int = 0
    amber_count: int = 0
    cost_exposure: float = 0.0


class ComponentHealth(ApiModel):
    part_code: str
    part_name: str
    category: str
    failure_probability: float
    health_index: float
    risk_tier: str
    rul_km: float
    rul_days: float
    model_confidence: float
    escalated: bool
    top_signal: str | None
    estimated_cost_impact: float


class ServiceEvent(ApiModel):
    job_card_id: int
    part_code: str
    part_name: str
    event_date: date
    event_type: str
    odometer_reading: int
    cost: float
    downtime_hours: float


class TelemetryPoint(ApiModel):
    week_start_date: date
    week_km: float
    odometer_km: int
    signals: dict[str, float]


class VehicleDetail(VehicleOut):
    components: list[ComponentHealth]
    service_history: list[ServiceEvent]
    telemetry: list[TelemetryPoint]


# --- rul ---------------------------------------------------------------------


class RulRow(ApiModel):
    vin: str
    part_code: str
    part_name: str
    customer_id: int
    customer_name: str
    model: str
    rul_days: float
    rul_km: float
    window_from_days: int
    window_to_days: int
    failure_probability: float
    risk_tier: str
    model_confidence: float
    degradation_trend: float
    urgency_band: str = Field(
        description="overdue | within_30_days | within_90_days | healthy"
    )
    lead_time_days: int
    estimated_cost_impact: float


class RulBands(ApiModel):
    """Counts per urgency band.

    Overdue is separated because a flat list starting with hundreds of zeros
    looks broken rather than urgent (spec section 9, RUL Explorer).
    """

    overdue: int
    within_30_days: int
    within_90_days: int
    healthy: int


class RulDetail(ApiModel):
    vin: str
    part_code: str
    part_name: str
    rul_km: float
    rul_days: float
    window_from_days: int
    window_to_days: int
    model_confidence: float
    degradation_trend: float
    health_index: float
    failure_probability: float
    risk_tier: str
    km_on_part: float
    design_life_km: int
    avg_km_per_day: float
    failure_threshold_index: float
    curve: list[CurvePoint]
    cross_check: str


class FilterOptions(ApiModel):
    """Every value the fleet filters can offer, within the caller's scope.

    A customer-scoped caller sees only the models and regions present in its
    own fleet - the filter menu must not leak the existence of another
    tenant's depots or vehicle variants.
    """

    models: list[str]
    variants: list[str]
    regions: list[str]
    vehicle_statuses: list[str]
