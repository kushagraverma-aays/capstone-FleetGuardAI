/**
 * One typed function per API endpoint. No component calls `request()`
 * directly; it calls one of these, and gets a typed result back.
 *
 * Filter objects mirror the query parameters the backend declares, so a screen
 * can hand its filter state straight through.
 */

import { request, requestBlob, type QueryParams } from "./client";
import type {
  ChatCapabilities,
  ChatRequest,
  ChatResponse,
  CostExposure,
  CustomerOut,
  DraftRequest,
  DraftResponse,
  FailureTrends,
  FleetComparison,
  NotificationAudience,
  NotificationOut,
  NotificationSeverity,
  NotificationStatus,
  Overview,
  Page,
  PartCorrelations,
  PartHistory,
  PartOut,
  PredictionDetail,
  PredictionOut,
  RiskTier,
  RuleDeployRequest,
  RuleOut,
  RulePreview,
  RulePreviewRequest,
  RulBands,
  RulDetail,
  RulRow,
  ScopeInfo,
  SortOrder,
  UrgencyBand,
  VehicleDetail,
  VehicleOut,
  WorkOrderCreate,
  WorkOrderOut,
  WorkOrderStatus,
  WorkOrderUpdate,
} from "./types";

// --- filter shapes -----------------------------------------------------------

export interface PageParams {
  limit?: number;
  offset?: number;
}

/** The list endpoints accept repeated values for these, which is how the
 *  multi-select filters on the Fleet screen work. */
export interface PredictionFilters extends PageParams {
  tier?: RiskTier[];
  customer_id?: number[];
  region?: string[];
  model?: string[];
  part_code?: string[];
  search?: string;
  max_rul_days?: number;
  escalated_only?: boolean;
  sort?: "probability" | "rul" | "vin" | "cost" | "health";
  order?: SortOrder;
}

export interface VehicleFilters extends PageParams {
  tier?: RiskTier[];
  customer_id?: number[];
  region?: string[];
  model?: string[];
  vehicle_status?: string[];
  search?: string;
  sort?: "vin" | "probability" | "rul" | "cost" | "km" | "model";
  order?: SortOrder;
}

export interface RulFilters extends PageParams {
  band?: UrgencyBand;
  tier?: RiskTier[];
  customer_id?: number[];
  region?: string[];
  model?: string[];
  part_code?: string[];
  search?: string;
}

export interface NotificationFilters extends PageParams {
  audience?: NotificationAudience[];
  severity?: NotificationSeverity[];
  alert_status?: NotificationStatus[];
  customer_id?: number[];
  search?: string;
}

export interface WorkOrderFilters extends PageParams {
  work_order_status?: WorkOrderStatus[];
  customer_id?: number[];
  vin?: string;
}

export interface ExportFilters {
  tier?: RiskTier[];
  customer_id?: number[];
  region?: string[];
  model?: string[];
  part_code?: string[];
  search?: string;
  sort?: PredictionFilters["sort"];
  order?: SortOrder;
}

const asQuery = (filters: object | undefined): QueryParams =>
  (filters ?? {}) as QueryParams;

// --- session -----------------------------------------------------------------

export const getScopeInfo = () => request<ScopeInfo>("/api/auth/me");

export const listCustomers = () => request<CustomerOut[]>("/api/customers");

// --- command centre ----------------------------------------------------------

export const getOverview = () => request<Overview>("/api/overview");

// --- fleet -------------------------------------------------------------------

export const listPredictions = (filters?: PredictionFilters) =>
  request<Page<PredictionOut>>("/api/predictions", { query: asQuery(filters) });

export const getPrediction = (vin: string, partCode: string) =>
  request<PredictionDetail>(
    `/api/predictions/${encodeURIComponent(vin)}/${encodeURIComponent(partCode)}`,
  );

export const listVehicles = (filters?: VehicleFilters) =>
  request<Page<VehicleOut>>("/api/vehicles", { query: asQuery(filters) });

export const getVehicle = (vin: string) =>
  request<VehicleDetail>(`/api/vehicles/${encodeURIComponent(vin)}`);

// --- RUL ---------------------------------------------------------------------

export const listRul = (filters?: RulFilters) =>
  request<Page<RulRow>>("/api/rul", { query: asQuery(filters) });

export const getRulBands = (filters?: Omit<RulFilters, "band" | keyof PageParams>) =>
  request<RulBands>("/api/rul/bands", { query: asQuery(filters) });

export const getRulDetail = (vin: string, partCode: string) =>
  request<RulDetail>(
    `/api/rul/${encodeURIComponent(vin)}/${encodeURIComponent(partCode)}`,
  );

// --- parts and rules ---------------------------------------------------------

export const listParts = () => request<PartOut[]>("/api/parts");

export const getPartHistory = (partCode: string) =>
  request<PartHistory>(`/api/parts/${encodeURIComponent(partCode)}/history`);

export const getPartCorrelations = (partCode: string) =>
  request<PartCorrelations>(
    `/api/parts/${encodeURIComponent(partCode)}/correlations`,
  );

export const listRules = () => request<RuleOut[]>("/api/rules");

export const getRule = (partCode: string) =>
  request<RuleOut>(`/api/rules/${encodeURIComponent(partCode)}`);

export const getRuleHistory = (partCode: string) =>
  request<RuleOut[]>(`/api/rules/${encodeURIComponent(partCode)}/history`);

export const previewRule = (payload: RulePreviewRequest) =>
  request<RulePreview>("/api/rules/preview", { method: "POST", body: payload });

export const deployRule = (payload: RuleDeployRequest) =>
  request<RuleOut>("/api/rules", { method: "POST", body: payload });

// --- analytics ---------------------------------------------------------------

export const getCostExposure = (dimension: "customer" | "component" | "region") =>
  request<CostExposure>("/api/analytics/cost-exposure", { query: { dimension } });

export const getFailureTrends = (months = 12) =>
  request<FailureTrends>("/api/analytics/failure-trends", { query: { months } });

export const getFleetComparison = () =>
  request<FleetComparison>("/api/analytics/fleet-comparison");

// --- workflow ----------------------------------------------------------------

export const listNotifications = (filters?: NotificationFilters) =>
  request<Page<NotificationOut>>("/api/notifications", { query: asQuery(filters) });

export const updateNotification = (id: number, status: NotificationStatus) =>
  request<NotificationOut>(`/api/notifications/${id}`, {
    method: "PATCH",
    body: { status },
  });

export const listWorkOrders = (filters?: WorkOrderFilters) =>
  request<Page<WorkOrderOut>>("/api/work-orders", { query: asQuery(filters) });

export const createWorkOrder = (payload: WorkOrderCreate) =>
  request<WorkOrderOut>("/api/work-orders", { method: "POST", body: payload });

export const updateWorkOrder = (id: number, payload: WorkOrderUpdate) =>
  request<WorkOrderOut>(`/api/work-orders/${id}`, { method: "PATCH", body: payload });

// --- export ------------------------------------------------------------------

export const exportPredictionsCsv = (filters?: ExportFilters) =>
  requestBlob("/api/export/predictions.csv", asQuery(filters));

// --- assistant ---------------------------------------------------------------

export const getChatCapabilities = () => request<ChatCapabilities>("/api/chat");

export const sendChatMessage = (payload: ChatRequest) =>
  request<ChatResponse>("/api/chat", { method: "POST", body: payload });

export const draftMessage = (payload: DraftRequest) =>
  request<DraftResponse>("/api/chat/draft", { method: "POST", body: payload });
