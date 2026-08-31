"""Response models for the overview, alerts, work orders and analytics screens."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from app.schemas.common import ApiModel


# --- overview (Command Centre) -----------------------------------------------


class OverviewKpis(ApiModel):
    vehicles_monitored: int
    components_tracked: int
    red_count: int
    amber_count: int
    green_count: int
    escalated_count: int
    inside_30_day_rul: int
    total_cost_exposure: float
    avoidable_cost: float
    open_notifications: int


class TierSlice(ApiModel):
    tier: str
    count: int
    share: float


class FailureTrendPoint(ApiModel):
    month: str
    failures: int
    preventive: int


class TopSignal(ApiModel):
    signal: str
    label: str
    mean_weight: float
    components: int = Field(
        description="Deployed rules in which this signal carries weight."
    )
    fleet_mean_value: float


class AttentionRow(ApiModel):
    vin: str
    part_code: str
    part_name: str
    customer_name: str
    failure_probability: float
    risk_tier: str
    rul_days: float
    escalated: bool
    escalation_reason: str | None
    estimated_cost_impact: float
    lead_time_days: int


class CustomerExposure(ApiModel):
    customer_id: int
    customer_name: str
    vehicles: int
    red_count: int
    cost_exposure: float
    exposure_per_vehicle: float


class Overview(ApiModel):
    scope_label: str
    computed_date: date | None
    kpis: OverviewKpis
    tiers: list[TierSlice]
    failure_trend: list[FailureTrendPoint]
    top_signals: list[TopSignal]
    needs_attention: list[AttentionRow]
    cost_by_customer: list[CustomerExposure]


# --- notifications -----------------------------------------------------------


class NotificationOut(ApiModel):
    id: int
    vin: str
    part_code: str
    part_name: str
    customer_id: int
    customer_name: str
    audience: str
    severity: str
    title: str
    message: str
    status: str
    created_at: datetime
    acknowledged_at: datetime | None


class NotificationUpdate(ApiModel):
    status: str = Field(
        description="acknowledged | dismissed | actioned | pending",
    )


# --- work orders -------------------------------------------------------------


class WorkOrderOut(ApiModel):
    id: int
    vin: str
    part_code: str
    part_name: str
    customer_id: int
    customer_name: str
    status: str
    scheduled_date: date | None
    notes: str | None
    created_at: datetime


class WorkOrderCreate(ApiModel):
    vin: str
    part_code: str
    scheduled_date: date | None = None
    notes: str | None = None
    status: str = Field(
        default="draft", description="draft | scheduled | completed"
    )


class WorkOrderUpdate(ApiModel):
    status: str | None = None
    scheduled_date: date | None = None
    notes: str | None = None


# --- analytics ---------------------------------------------------------------


class CostExposureRow(ApiModel):
    key: str
    label: str
    exposure: float
    avoidable: float
    red_count: int
    components: int


class CostExposure(ApiModel):
    dimension: str
    total_exposure: float
    total_avoidable: float
    rows: list[CostExposureRow]


class ComponentTrendPoint(ApiModel):
    month: str
    part_code: str
    part_name: str
    failures: int


class FailureTrends(ApiModel):
    months: list[str]
    total_by_month: list[FailureTrendPoint]
    by_component: list[ComponentTrendPoint]
    signal_prevalence: list[TopSignal]


class FleetComparisonRow(ApiModel):
    customer_id: int
    customer_name: str
    region: str
    contract_tier: str
    vehicles: int
    failures_12m: int
    failures_per_100_vehicles: float
    red_share: float
    mean_health_index: float
    cost_exposure: float
    exposure_per_vehicle: float
    mean_km_per_day: float


class FleetComparison(ApiModel):
    fleet_mean_health_index: float
    fleet_failures_per_100_vehicles: float
    rows: list[FleetComparisonRow]
