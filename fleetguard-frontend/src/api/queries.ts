/**
 * TanStack Query hooks - all server state in the product lives here.
 *
 * Two rules hold across the whole file:
 *
 *  1. **Every key begins with the scope.** The API already refuses to serve
 *     another tenant's data, but a cache keyed without the scope would hand
 *     the previous tenant's rows to the next render before the refetch lands.
 *     `scopeKey` in the key makes switching customers a cache miss, which is
 *     the behaviour a viewer expects when they change who they are looking at.
 *  2. **Mutations invalidate the scope's subtree**, not individual keys, so a
 *     write is never followed by a screen showing the pre-write number.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ApiError } from "./client";
import * as api from "./endpoints";
import type {
  ChatRequest,
  DraftRequest,
  LoginRequest,
  NotificationStatus,
  RuleDeployRequest,
  RulePreviewRequest,
  UrgencyBand,
  WorkOrderCreate,
  WorkOrderUpdate,
} from "./types";
import { useScope, useSession } from "@/state/session";
import { scopeKey as scopeKeyFor, type ScopeValue } from "./session";

/** Key factory. Everything the app caches hangs off `["fleetguard", scope]`. */
export const keys = {
  root: (scope: ScopeValue) => ["fleetguard", scopeKeyFor(scope)] as const,
  scopeInfo: (scope: ScopeValue) => [...keys.root(scope), "scope-info"] as const,
  customers: (scope: ScopeValue) => [...keys.root(scope), "customers"] as const,
  filterOptions: (scope: ScopeValue) => [...keys.root(scope), "filter-options"] as const,
  overview: (scope: ScopeValue) => [...keys.root(scope), "overview"] as const,
  predictions: (scope: ScopeValue, filters: object) =>
    [...keys.root(scope), "predictions", filters] as const,
  prediction: (scope: ScopeValue, vin: string, part: string) =>
    [...keys.root(scope), "prediction", vin, part] as const,
  vehicles: (scope: ScopeValue, filters: object) =>
    [...keys.root(scope), "vehicles", filters] as const,
  vehicle: (scope: ScopeValue, vin: string) =>
    [...keys.root(scope), "vehicle", vin] as const,
  rul: (scope: ScopeValue, filters: object) => [...keys.root(scope), "rul", filters] as const,
  rulBands: (scope: ScopeValue, filters: object) =>
    [...keys.root(scope), "rul-bands", filters] as const,
  rulDetail: (scope: ScopeValue, vin: string, part: string) =>
    [...keys.root(scope), "rul-detail", vin, part] as const,
  parts: (scope: ScopeValue) => [...keys.root(scope), "parts"] as const,
  partHistory: (scope: ScopeValue, part: string) =>
    [...keys.root(scope), "part-history", part] as const,
  partCorrelations: (scope: ScopeValue, part: string) =>
    [...keys.root(scope), "part-correlations", part] as const,
  rules: (scope: ScopeValue) => [...keys.root(scope), "rules"] as const,
  rule: (scope: ScopeValue, part: string) => [...keys.root(scope), "rule", part] as const,
  ruleHistory: (scope: ScopeValue, part: string) =>
    [...keys.root(scope), "rule-history", part] as const,
  rulePreview: (scope: ScopeValue, part: string, signals: string[] | null) =>
    [...keys.root(scope), "rule-preview", part, signals] as const,
  costExposure: (scope: ScopeValue, dimension: string) =>
    [...keys.root(scope), "cost-exposure", dimension] as const,
  failureTrends: (scope: ScopeValue, months: number) =>
    [...keys.root(scope), "failure-trends", months] as const,
  fleetComparison: (scope: ScopeValue) => [...keys.root(scope), "fleet-comparison"] as const,
  notifications: (scope: ScopeValue, filters: object) =>
    [...keys.root(scope), "notifications", filters] as const,
  workOrders: (scope: ScopeValue, filters: object) =>
    [...keys.root(scope), "work-orders", filters] as const,
  chatCapabilities: () => ["fleetguard", "chat-capabilities"] as const,
};

/**
 * Everything this client throws is an `ApiError`, so tell TanStack Query that
 * once and every `error` in the product is typed with `slug`, `status` and
 * `problems` on it - no casting at the call site.
 */
declare module "@tanstack/react-query" {
  interface Register {
    defaultError: ApiError;
  }
}

// --- session -----------------------------------------------------------------

/** Who the viewer is and what they may do. `can_write` and `can_manage_rules`
 *  drive the disabled states; the client does not re-derive the role rules. */
export function useScopeInfo() {
  const scope = useScope();
  return useQuery({
    queryKey: keys.scopeInfo(scope),
    queryFn: () => api.getScopeInfo(),
    staleTime: 5 * 60_000,
  });
}

/**
 * The seeded sign-ins the login screen offers.
 *
 * A 404 is the expected answer once the backend enforces authentication, not a
 * failure - the screen falls back to the plain email and password form - so it
 * is never retried and never surfaced as an error.
 */
export function useDemoAccounts() {
  return useQuery({
    queryKey: ["fleetguard", "demo-accounts"] as const,
    queryFn: () => api.getDemoAccounts(),
    retry: false,
    staleTime: Infinity,
  });
}

/**
 * Sign in.
 *
 * The whole cache is cleared on success rather than invalidated: the next
 * identity may see fewer vehicles than this one, and an invalidated entry is
 * still served while it refetches, which would show one tenant's rows to the
 * next person for as long as the request takes.
 */
export function useLogin() {
  const client = useQueryClient();
  const { signIn } = useSession();

  return useMutation({
    mutationFn: (body: LoginRequest) => api.login(body),
    onSuccess: (token) => {
      client.clear();
      signIn(token.access_token, {
        email: token.email,
        fullName: token.full_name,
        role: token.role,
        customerId: token.customer_id,
      });
    },
  });
}

export function useCustomers() {
  const scope = useScope();
  return useQuery({
    queryKey: keys.customers(scope),
    queryFn: () => api.listCustomers(),
    staleTime: 5 * 60_000,
  });
}

/** Filter menu contents. Rarely changes, so it is cached for the session. */
export function useFilterOptions() {
  const scope = useScope();
  return useQuery({
    queryKey: keys.filterOptions(scope),
    queryFn: () => api.getFilterOptions(),
    staleTime: 10 * 60_000,
  });
}

// --- command centre ----------------------------------------------------------

export function useOverview() {
  const scope = useScope();
  return useQuery({
    queryKey: keys.overview(scope),
    queryFn: () => api.getOverview(),
  });
}

// --- fleet -------------------------------------------------------------------

export function usePredictions(filters: api.PredictionFilters) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.predictions(scope, filters),
    queryFn: () => api.listPredictions(filters),
  });
}

export function usePrediction(vin: string | undefined, partCode: string | undefined) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.prediction(scope, vin ?? "", partCode ?? ""),
    queryFn: () => api.getPrediction(vin as string, partCode as string),
    enabled: Boolean(vin && partCode),
  });
}

export function useVehicles(filters: api.VehicleFilters) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.vehicles(scope, filters),
    queryFn: () => api.listVehicles(filters),
  });
}

export function useVehicle(vin: string | undefined) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.vehicle(scope, vin ?? ""),
    queryFn: () => api.getVehicle(vin as string),
    enabled: Boolean(vin),
  });
}

// --- RUL ---------------------------------------------------------------------

export function useRul(filters: api.RulFilters) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.rul(scope, filters),
    queryFn: () => api.listRul(filters),
  });
}

export function useRulBands(filters: Omit<api.RulFilters, "band" | "limit" | "offset">) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.rulBands(scope, filters),
    queryFn: () => api.getRulBands(filters),
  });
}

export function useRulDetail(vin: string | undefined, partCode: string | undefined) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.rulDetail(scope, vin ?? "", partCode ?? ""),
    queryFn: () => api.getRulDetail(vin as string, partCode as string),
    enabled: Boolean(vin && partCode),
  });
}

// --- parts and rules ---------------------------------------------------------

export function useParts() {
  const scope = useScope();
  return useQuery({
    queryKey: keys.parts(scope),
    queryFn: () => api.listParts(),
    staleTime: 60_000,
  });
}

export function usePartHistory(partCode: string | undefined) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.partHistory(scope, partCode ?? ""),
    queryFn: () => api.getPartHistory(partCode as string),
    enabled: Boolean(partCode),
  });
}

export function usePartCorrelations(partCode: string | undefined) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.partCorrelations(scope, partCode ?? ""),
    queryFn: () => api.getPartCorrelations(partCode as string),
    enabled: Boolean(partCode),
  });
}

export function useRules() {
  const scope = useScope();
  return useQuery({
    queryKey: keys.rules(scope),
    queryFn: () => api.listRules(),
  });
}

export function useRule(partCode: string | undefined) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.rule(scope, partCode ?? ""),
    queryFn: () => api.getRule(partCode as string),
    enabled: Boolean(partCode),
  });
}

export function useRuleHistory(partCode: string | undefined) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.ruleHistory(scope, partCode ?? ""),
    queryFn: () => api.getRuleHistory(partCode as string),
    enabled: Boolean(partCode),
  });
}

/**
 * Rule Studio step 3 re-previews on every signal toggle, so this is a query
 * keyed by the selected signals rather than a mutation: toggling a signal off
 * and back on is then instant from cache, and the weights animate rather than
 * flashing through a loading state. `placeholderData` keeps the previous
 * preview on screen while the next one is fetched.
 */
export function useRulePreview(payload: RulePreviewRequest | null) {
  const scope = useScope();
  const signals = payload?.signals ?? null;
  return useQuery({
    queryKey: keys.rulePreview(scope, payload?.part_code ?? "", signals),
    queryFn: () => api.previewRule(payload as RulePreviewRequest),
    enabled: Boolean(payload?.part_code),
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });
}

// --- analytics ---------------------------------------------------------------

export function useCostExposure(dimension: "customer" | "component" | "region") {
  const scope = useScope();
  return useQuery({
    queryKey: keys.costExposure(scope, dimension),
    queryFn: () => api.getCostExposure(dimension),
  });
}

export function useFailureTrends(months = 12) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.failureTrends(scope, months),
    queryFn: () => api.getFailureTrends(months),
  });
}

export function useFleetComparison() {
  const scope = useScope();
  return useQuery({
    queryKey: keys.fleetComparison(scope),
    queryFn: () => api.getFleetComparison(),
  });
}

// --- workflow ----------------------------------------------------------------

export function useNotifications(filters: api.NotificationFilters) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.notifications(scope, filters),
    queryFn: () => api.listNotifications(filters),
  });
}

export function useWorkOrders(filters: api.WorkOrderFilters) {
  const scope = useScope();
  return useQuery({
    queryKey: keys.workOrders(scope, filters),
    queryFn: () => api.listWorkOrders(filters),
  });
}

/**
 * Acknowledging or dismissing an alert updates the row before the server
 * answers - the operator is working through an inbox and a 200 ms pause per
 * click reads as lag. On failure the previous cache is restored, so a rejected
 * write never leaves a wrong status on screen.
 */
export function useUpdateNotification() {
  const scope = useScope();
  const queryClient = useQueryClient();

  return useMutation<
    Awaited<ReturnType<typeof api.updateNotification>>,
    ApiError,
    { id: number; status: NotificationStatus },
    { previous: [readonly unknown[], unknown][] }
  >({
    mutationFn: ({ id, status }) => api.updateNotification(id, status),
    onMutate: async ({ id, status }) => {
      const prefix = [...keys.root(scope), "notifications"];
      await queryClient.cancelQueries({ queryKey: prefix });
      const previous = queryClient.getQueriesData({ queryKey: prefix });

      queryClient.setQueriesData<{ items: { id: number; status: string }[] }>(
        { queryKey: prefix },
        (page) =>
          page
            ? {
                ...page,
                items: page.items.map((item) =>
                  item.id === id ? { ...item, status } : item,
                ),
              }
            : page,
      );
      return { previous: previous as [readonly unknown[], unknown][] };
    },
    onError: (_error, _variables, context) => {
      for (const [key, data] of context?.previous ?? []) {
        queryClient.setQueryData(key, data);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: keys.root(scope) });
    },
  });
}

export function useCreateWorkOrder() {
  const scope = useScope();
  const queryClient = useQueryClient();
  return useMutation<
    Awaited<ReturnType<typeof api.createWorkOrder>>,
    ApiError, WorkOrderCreate>({
    mutationFn: (payload) => api.createWorkOrder(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.root(scope) });
    },
  });
}

export function useUpdateWorkOrder() {
  const scope = useScope();
  const queryClient = useQueryClient();
  return useMutation<
    Awaited<ReturnType<typeof api.updateWorkOrder>>,
    ApiError,
    { id: number; payload: WorkOrderUpdate }
  >({
    mutationFn: ({ id, payload }) => api.updateWorkOrder(id, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.root(scope) });
    },
  });
}

export function useDeployRule() {
  const scope = useScope();
  const queryClient = useQueryClient();
  return useMutation<
    Awaited<ReturnType<typeof api.deployRule>>,
    ApiError, RuleDeployRequest>({
    mutationFn: (payload) => api.deployRule(payload),
    onSuccess: () => {
      // A deployed rule changes probabilities, tiers, cost and RUL the next
      // time scoring runs, so nothing in this scope stays trustworthy.
      void queryClient.invalidateQueries({ queryKey: keys.root(scope) });
    },
  });
}

/**
 * Restore an earlier rule version.
 *
 * Same cache consequence as a deploy - it writes a new active version - so it
 * invalidates the whole scope rather than just the rule keys.
 */
export function useRestoreRule() {
  const scope = useScope();
  const queryClient = useQueryClient();
  return useMutation<
    Awaited<ReturnType<typeof api.restoreRule>>,
    ApiError,
    { partCode: string; version: number }
  >({
    mutationFn: ({ partCode, version }) => api.restoreRule(partCode, version),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.root(scope) });
    },
  });
}

// --- assistant ---------------------------------------------------------------

export function useChatCapabilities() {
  return useQuery({
    queryKey: keys.chatCapabilities(),
    queryFn: () => api.getChatCapabilities(),
    staleTime: Infinity,
  });
}

export function useSendChatMessage() {
  return useMutation<
    Awaited<ReturnType<typeof api.sendChatMessage>>,
    ApiError, ChatRequest>({
    mutationFn: (payload) => api.sendChatMessage(payload),
  });
}

export function useDraftMessage() {
  return useMutation<
    Awaited<ReturnType<typeof api.draftMessage>>,
    ApiError, DraftRequest>({
    mutationFn: (payload) => api.draftMessage(payload),
  });
}

/** Re-exported so screens can type a band filter without importing types. */
export type { UrgencyBand };
