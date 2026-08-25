from __future__ import annotations

from pydantic import BaseModel, Field


class SignalStat(BaseModel):
    signal: str
    label: str
    correlation: float
    correlation_pct: float
    weight: float = 0.0
    included: bool = True


class PrecursorSignal(BaseModel):
    signal: str
    label: str
    count: int


class OverviewOut(BaseModel):
    components_under_watch: int
    high_failure_probability: int
    inside_30day_rul: int
    precursor_patterns_validated: int
    action_threshold: float
    top_precursor_signals: list[PrecursorSignal]
    computed_date: str | None = None


class PartOut(BaseModel):
    part_code: str
    part_name: str
    category: str
    design_life_km: int


class MonthlyCount(BaseModel):
    month: str
    count: int


class PartHistoryOut(BaseModel):
    part_code: str
    part_name: str
    historical_failures: int
    affected_vins: int
    avg_mileage_at_failure: int
    monthly_counts: list[MonthlyCount]


class CorrelationsOut(BaseModel):
    part_code: str
    method: str
    signals: list[SignalStat]


class RuleOut(BaseModel):
    rule_id: int | None = None
    part_code: str
    formula: str
    precision: float
    coverage: float
    days_to_alert: int
    sample_failures: int
    created_at: str | None = None
    signals: list[SignalStat]
    excluded: list[SignalStat] = []


class RuleRequest(BaseModel):
    part_code: str
    signals: list[str] = Field(default_factory=list)


class Driver(BaseModel):
    signal: str
    label: str
    value: float
    share: float


class TrendPoint(BaseModel):
    week: str
    probability: float


class CurvePoint(BaseModel):
    km: float
    health: float
    projected: bool


class PartRisk(BaseModel):
    part_code: str
    part_name: str
    failure_probability: float
    rul_days: int
    risk_tier: str


class VehicleRiskOut(BaseModel):
    vin: str
    model: str
    region: str
    fleet_operator: str
    parts_tracked: int
    top_probability: float
    top_part: str
    min_rul_days: int
    risk_tier: str
    parts: list[PartRisk]


class PredictionDetailOut(BaseModel):
    vin: str
    model: str
    region: str
    part_code: str
    part_name: str
    failure_probability: float
    risk_tier: str
    escalated: bool = False
    escalation_reason: str | None = None
    health_index: float
    window_from_days: int
    window_to_days: int
    top_signal: str
    top_signal_label: str
    top_signal_share: float
    drivers: list[Driver]
    trend: list[TrendPoint]
    rule_id: int | None
    formula: str | None
    crosscheck: str


class RulDetailOut(BaseModel):
    vin: str
    model: str
    part_code: str
    part_name: str
    rul_km: float
    rul_days: int
    design_life_km: int
    model_confidence: float
    degradation_trend: float
    health_index: float
    failure_threshold: float
    curve: list[CurvePoint]
    crosscheck: str


class NotificationOut(BaseModel):
    id: int
    vin: str
    part_code: str
    audience: str
    severity: str
    message: str
    status: str