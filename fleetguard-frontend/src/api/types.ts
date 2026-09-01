/**
 * TypeScript mirrors of the backend's Pydantic response models.
 *
 * These are hand-mirrored from the OpenAPI document served at /openapi.json
 * rather than generated, because the generated output for this API is a wall
 * of `components["schemas"]["..."]` indirection that reads badly at the call
 * site. The rule is that every field name and type here matches the schema
 * exactly; when a response model changes, this file changes with it.
 *
 * Regenerate the reference to diff against:
 *   curl http://localhost:8000/openapi.json > openapi.json
 */

// --- shared ------------------------------------------------------------------

/** Every list endpoint answers in this shape, so one table and one pagination
 *  control serve the whole product. */
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

/** Risk tiers are uppercase on the wire (spec 6.7). */
export type RiskTier = "RED" | "AMBER" | "GREEN";

export type UrgencyBand = "overdue" | "within_30_days" | "within_90_days" | "healthy";

export type NotificationAudience = "vendor" | "fleet_owner";
export type NotificationSeverity = "critical" | "high" | "medium";
export type NotificationStatus = "pending" | "acknowledged" | "dismissed" | "actioned";
export type WorkOrderStatus = "draft" | "scheduled" | "completed" | "cancelled";

export type SortOrder = "asc" | "desc";

/**
 * **Units on the wire, which are not uniform - read this before formatting.**
 *
 * Fractions in 0-1: `failure_probability`, `model_confidence`, `weight`,
 * `correlation`, `precision`, `coverage`, `red_share`, `TierSlice.share`,
 * `mean_weight`.
 *
 * Already scaled to 0-100: every field named `*_share` on a prediction or a
 * rule signal (`DriverOut.share`, `RuleSignalOut.share`,
 * `PredictionOut.top_signal_share`), plus `life_used_pct`,
 * `median_life_used_pct`, `health_index` and `mean_health_index`.
 *
 * `formatPercent(value, { alreadyScaled: true })` is for the second group.
 * Getting it wrong renders "3,630% of stress", which is how this was found.
 */

// --- auth and scope ----------------------------------------------------------

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type?: string;
  expires_in_minutes: number;
  role: string;
  customer_id: number | null;
  full_name: string;
  email: string;
}

/** One seeded sign-in offered on the login screen.
 *
 *  Served only while the backend has `AUTH_ENABLED=false`; the endpoint 404s
 *  once enforcement is on, and the form falls back to plain email and
 *  password. Nothing in the UI hardcodes a credential. */
export interface DemoAccount {
  email: string;
  password: string;
  full_name: string;
  role: string;
  role_label: string;
  description: string;
  customer_id: number | null;
  customer_name: string | null;
}

export interface DemoAccounts {
  accounts: DemoAccount[];
  note: string;
}

/** What the UI is allowed to do. Drive disabled states from `can_write` and
 *  `can_manage_rules` rather than re-deriving the role rules in the client. */
export interface ScopeInfo {
  customer_id: number | null;
  customer_name?: string | null;
  role: string;
  email?: string | null;
  full_name?: string | null;
  is_manufacturer: boolean;
  can_write: boolean;
  can_manage_rules: boolean;
  auth_enabled: boolean;
}

export interface CustomerOut {
  customer_id: number;
  name: string;
  region: string;
  contact_email: string;
  contract_tier: string;
  vehicle_count?: number;
  red_count?: number;
  cost_exposure?: number;
}

/** Distinct values the fleet filters offer, computed server-side within the
 *  caller's scope. Built from the whole result set, not from a loaded page. */
export interface FilterOptions {
  models: string[];
  variants: string[];
  regions: string[];
  vehicle_statuses: string[];
}

// --- overview ----------------------------------------------------------------

export interface OverviewKpis {
  vehicles_monitored: number;
  components_tracked: number;
  red_count: number;
  amber_count: number;
  green_count: number;
  escalated_count: number;
  inside_30_day_rul: number;
  total_cost_exposure: number;
  avoidable_cost: number;
  open_notifications: number;
}

export interface TierSlice {
  tier: RiskTier;
  count: number;
  share: number;
}

export interface FailureTrendPoint {
  month: string;
  failures: number;
  preventive: number;
}

export interface TopSignal {
  signal: string;
  label: string;
  mean_weight: number;
  components: number;
  fleet_mean_value: number;
}

export interface AttentionRow {
  vin: string;
  part_code: string;
  part_name: string;
  customer_name: string;
  failure_probability: number;
  risk_tier: RiskTier;
  rul_days: number;
  escalated: boolean;
  escalation_reason: string | null;
  estimated_cost_impact: number;
  lead_time_days: number;
}

export interface CustomerExposure {
  customer_id: number;
  customer_name: string;
  vehicles: number;
  red_count: number;
  cost_exposure: number;
  exposure_per_vehicle: number;
}

export interface Overview {
  scope_label: string;
  computed_date: string | null;
  kpis: OverviewKpis;
  tiers: TierSlice[];
  failure_trend: FailureTrendPoint[];
  top_signals: TopSignal[];
  needs_attention: AttentionRow[];
  cost_by_customer: CustomerExposure[];
}

// --- predictions and vehicles ------------------------------------------------

export interface PredictionOut {
  vin: string;
  part_code: string;
  part_name: string;
  customer_id: number;
  customer_name: string;
  model: string;
  variant: string;
  region: string;
  failure_probability: number;
  risk_tier: RiskTier;
  health_index: number;
  rul_km: number;
  rul_days: number;
  window_from_days: number;
  window_to_days: number;
  model_confidence: number;
  degradation_trend: number;
  top_signal: string | null;
  top_signal_share: number;
  escalated: boolean;
  escalation_reason: string | null;
  estimated_cost_impact: number;
  computed_date: string;
}

export interface DriverOut {
  signal: string;
  label: string;
  value: number;
  weight: number;
  contribution: number;
  share: number;
}

export interface TrendPoint {
  week: string;
  probability: number;
  health_index: number;
}

export interface CurvePoint {
  km_on_part: number;
  health_index: number;
  projected: boolean;
}

export interface CostBreakdown {
  unplanned_cost: number;
  planned_cost: number;
  avoidable_cost: number;
  estimated_cost_impact: number;
}

export interface PredictionDetail extends PredictionOut {
  drivers: DriverOut[];
  trend: TrendPoint[];
  curve: CurvePoint[];
  cost: CostBreakdown;
  rule: RuleOut | null;
  /** The sentence that reconciles failure probability with RUL for this
   *  component. Rendered verbatim - it is the product's own cross-check. */
  cross_check: string;
  km_on_part: number;
  design_life_km: number;
  life_used_pct: number;
  lead_time_days: number;
}

export interface VehicleOut {
  vin: string;
  customer_id: number;
  customer_name: string;
  model: string;
  variant: string;
  region: string;
  registration_date: string;
  total_km_driven: number;
  avg_km_per_day: number;
  status: string;
  worst_part_code?: string | null;
  worst_part_name?: string | null;
  worst_probability?: number;
  risk_tier?: RiskTier;
  min_rul_days?: number;
  red_count?: number;
  amber_count?: number;
  cost_exposure?: number;
}

export interface ComponentHealth {
  part_code: string;
  part_name: string;
  category: string;
  failure_probability: number;
  health_index: number;
  risk_tier: RiskTier;
  rul_km: number;
  rul_days: number;
  model_confidence: number;
  escalated: boolean;
  top_signal: string | null;
  estimated_cost_impact: number;
}

export interface ServiceEvent {
  job_card_id: number;
  part_code: string;
  part_name: string;
  event_date: string;
  event_type: string;
  odometer_reading: number;
  cost: number;
  downtime_hours: number;
}

export interface TelemetryPoint {
  week_start_date: string;
  week_km: number;
  odometer_km: number;
  signals: Record<string, number>;
}

export interface VehicleDetail extends VehicleOut {
  components: ComponentHealth[];
  service_history: ServiceEvent[];
  telemetry: TelemetryPoint[];
}

// --- RUL ---------------------------------------------------------------------

export interface RulRow {
  vin: string;
  part_code: string;
  part_name: string;
  customer_id: number;
  customer_name: string;
  model: string;
  rul_days: number;
  rul_km: number;
  window_from_days: number;
  window_to_days: number;
  failure_probability: number;
  risk_tier: RiskTier;
  model_confidence: number;
  degradation_trend: number;
  urgency_band: UrgencyBand;
  lead_time_days: number;
  estimated_cost_impact: number;
}

export interface RulBands {
  overdue: number;
  within_30_days: number;
  within_90_days: number;
  healthy: number;
}

export interface RulDetail {
  vin: string;
  part_code: string;
  part_name: string;
  rul_km: number;
  rul_days: number;
  window_from_days: number;
  window_to_days: number;
  model_confidence: number;
  degradation_trend: number;
  health_index: number;
  failure_probability: number;
  risk_tier: RiskTier;
  km_on_part: number;
  design_life_km: number;
  avg_km_per_day: number;
  failure_threshold_index: number;
  curve: CurvePoint[];
  cross_check: string;
}

// --- parts, correlations and rules -------------------------------------------

export interface PartOut {
  part_code: string;
  part_name: string;
  category: string;
  design_life_km: number;
  unit_cost: number;
  lead_time_days: number;
  labour_hours: number;
  tracked_vehicles?: number;
  failures_12m?: number;
  red_count?: number;
  has_active_rule?: boolean;
  rule_precision?: number | null;
  rule_coverage?: number | null;
  rule_days_to_alert?: number | null;
}

export interface PartHistoryPoint {
  month: string;
  failures: number;
  preventive: number;
}

export interface PartHistory {
  part_code: string;
  part_name: string;
  design_life_km: number;
  total_failures: number;
  total_preventive: number;
  median_km_at_failure: number;
  median_life_used_pct: number;
  mean_downtime_hours: number;
  warranty_claims: number;
  warranty_amount: number;
  monthly: PartHistoryPoint[];
}

export interface SignalCorrelationOut {
  signal: string;
  label: string;
  correlation: number;
  raw_correlation: number;
  p_value: number;
  logit_coefficient: number;
  mean_when_failed: number;
  mean_when_healthy: number;
}

export interface PartCorrelations {
  part_code: string;
  part_name: string;
  sample_rows: number;
  sample_failures: number;
  correlations: SignalCorrelationOut[];
  suggested_signals: string[];
}

export interface RuleSignalOut {
  signal: string;
  label: string;
  correlation: number;
  weight: number;
  share: number;
  included: boolean;
}

export interface RuleOut {
  rule_id: number;
  part_code: string;
  part_name: string;
  version: number;
  formula: string;
  precision: number;
  coverage: number;
  days_to_alert: number;
  sample_failures: number;
  is_active: boolean;
  created_by: string;
  created_at: string;
  signals: RuleSignalOut[];
}

export interface BacktestMetrics {
  precision: number;
  coverage: number;
  days_to_alert: number;
  sample_failures: number;
  alert_episodes: number;
  true_positive_episodes: number;
  caught_failures: number;
  alert_threshold: number;
  /** Episodes still running when the data ends: excluded from precision
   *  because their outcome is not yet observable. */
  censored_episodes?: number;
}

export interface RulePreview {
  part_code: string;
  part_name: string;
  formula: string;
  selected_signals: string[];
  weights: RuleSignalOut[];
  correlations: SignalCorrelationOut[];
  metrics: BacktestMetrics;
  weight_total: number;
}

export interface RulePreviewRequest {
  part_code: string;
  signals?: string[] | null;
}

export interface RuleDeployRequest {
  part_code: string;
  signals?: string[] | null;
  note?: string | null;
}

// --- analytics ---------------------------------------------------------------

export interface CostExposureRow {
  key: string;
  label: string;
  exposure: number;
  avoidable: number;
  red_count: number;
  components: number;
}

export interface CostExposure {
  dimension: string;
  total_exposure: number;
  total_avoidable: number;
  rows: CostExposureRow[];
}

export interface ComponentTrendPoint {
  month: string;
  part_code: string;
  part_name: string;
  failures: number;
}

export interface FailureTrends {
  months: string[];
  total_by_month: FailureTrendPoint[];
  by_component: ComponentTrendPoint[];
  signal_prevalence: TopSignal[];
}

export interface FleetComparisonRow {
  customer_id: number;
  customer_name: string;
  region: string;
  contract_tier: string;
  vehicles: number;
  failures_12m: number;
  failures_per_100_vehicles: number;
  red_share: number;
  mean_health_index: number;
  cost_exposure: number;
  exposure_per_vehicle: number;
  mean_km_per_day: number;
}

export interface FleetComparison {
  fleet_mean_health_index: number;
  fleet_failures_per_100_vehicles: number;
  rows: FleetComparisonRow[];
}

// --- workflow ----------------------------------------------------------------

export interface NotificationOut {
  id: number;
  vin: string;
  part_code: string;
  part_name: string;
  customer_id: number;
  customer_name: string;
  audience: NotificationAudience;
  severity: NotificationSeverity;
  title: string;
  message: string;
  status: NotificationStatus;
  created_at: string;
  acknowledged_at: string | null;
}

export interface NotificationUpdate {
  status: NotificationStatus;
}

export interface WorkOrderOut {
  id: number;
  vin: string;
  part_code: string;
  part_name: string;
  customer_id: number;
  customer_name: string;
  status: WorkOrderStatus;
  scheduled_date: string | null;
  notes: string | null;
  created_at: string;
}

export interface WorkOrderCreate {
  vin: string;
  part_code: string;
  scheduled_date?: string | null;
  notes?: string | null;
  status?: WorkOrderStatus;
}

export interface WorkOrderUpdate {
  status?: WorkOrderStatus | null;
  scheduled_date?: string | null;
  notes?: string | null;
}

// --- assistant ---------------------------------------------------------------

export interface ChatTool {
  name: string;
  description: string;
}

export interface ChatCapabilities {
  available: boolean;
  model: string;
  max_tool_rounds: number;
  tools: ChatTool[];
  suggested_questions: string[];
  grounding: string;
}

export interface ChatTurn {
  role: string;
  content: string;
}

export interface ChatRequest {
  message: string;
  history?: ChatTurn[] | null;
}

/** What a citation chip expands into: the tool, the arguments the loop chose,
 *  and the raw JSON the answer was built from. */
export interface Citation {
  tool: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
  duration_ms: number;
}

export interface ChatResponse {
  reply: string;
  tools_used: string[];
  data_cited: Citation[];
  rounds: number;
  truncated: boolean;
  hit_round_limit: boolean;
}

export interface DraftRequest {
  vin: string;
  part: string;
  audience: NotificationAudience;
}

export interface DraftResponse {
  message: string;
  audience: NotificationAudience;
  vin: string;
  part: string;
  facts: Record<string, unknown>;
  truncated: boolean;
}
