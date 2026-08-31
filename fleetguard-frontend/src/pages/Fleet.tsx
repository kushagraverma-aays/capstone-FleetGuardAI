/**
 * Fleet - the workhorse list.
 *
 * Two ways to look at the same fleet, because operators genuinely have two
 * questions. **By component** is the default: one row per (vehicle, part), the
 * unit of work an operator schedules, and the only view that can be filtered
 * by component or exported - the CSV export endpoint is component-level too.
 * **By vehicle** rolls that up to one row per truck showing its worst
 * component, which is what a customer conversation is about.
 *
 * All filter state lives in the URL. That makes every view a link - the
 * Command Centre's "all red components" is just `/fleet?tier=RED` - and it
 * means the back button undoes a filter rather than leaving the screen.
 */

import { Download, Filter, Layers, SlidersHorizontal, Truck } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { exportPredictionsCsv } from "@/api/endpoints";
import {
  useCustomers,
  useFilterOptions,
  useParts,
  usePredictions,
  useVehicles,
} from "@/api/queries";
import type { PredictionOut, RiskTier, VehicleOut } from "@/api/types";
import { PredictionDrawer } from "@/components/fleet/PredictionDrawer";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { DataTable, type Column, type SortState } from "@/components/ui/DataTable";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { AppliedFilters, FilterMenu } from "@/components/ui/FilterMenu";
import { SearchInput } from "@/components/ui/Input";
import { Menu, MenuItem, MenuLabel } from "@/components/ui/Menu";
import { Pagination } from "@/components/ui/Pagination";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { formatCurrency, formatKm, formatNumber, formatPercent, formatRulDays } from "@/lib/format";
import { TIER_ORDER, tierStyle } from "@/lib/risk";

const PAGE_SIZE = 100;

type ViewMode = "components" | "vehicles";

/** The chips above the table. Each is a filter combination an operator asks
 *  for by name, so it is worth one click rather than three menus. */
const SAVED_VIEWS = [
  {
    id: "red",
    label: "Red this week",
    hint: "Components at or above a 70% chance of failing",
    params: { tier: "RED", max_rul: "", escalated: "" },
  },
  {
    id: "overdue",
    label: "Overdue",
    hint: "Past the projected end of useful life",
    params: { tier: "", max_rul: "0", escalated: "" },
  },
  {
    id: "inside30",
    label: "Inside 30 days",
    hint: "Actionable this month",
    params: { tier: "", max_rul: "30", escalated: "" },
  },
  {
    id: "escalated",
    label: "Escalated on life",
    hint: "Lifted to red because life ran out, not because probability crossed",
    params: { tier: "", max_rul: "", escalated: "true" },
  },
] as const;

export default function FleetPage() {
  const [params, setParams] = useSearchParams();
  const toast = useToast();

  const mode: ViewMode = params.get("view") === "vehicles" ? "vehicles" : "components";
  const search = params.get("q") ?? "";
  const offset = Number.parseInt(params.get("offset") ?? "0", 10) || 0;
  const tiers = params.getAll("tier") as RiskTier[];
  const customerIds = params.getAll("customer").map(Number).filter(Number.isFinite);
  const regions = params.getAll("region");
  const models = params.getAll("model");
  const partCodes = params.getAll("part");
  const maxRul = params.get("max_rul");
  const escalatedOnly = params.get("escalated") === "true";
  const sort: SortState = {
    key: params.get("sort") ?? "probability",
    order: params.get("order") === "asc" ? "asc" : "desc",
  };

  const [selected, setSelected] = useState<{ vin: string; partCode: string } | null>(null);
  const [hiddenColumns, setHiddenColumns] = useState<string[]>([]);
  const [exporting, setExporting] = useState(false);

  const { data: customers } = useCustomers();
  const { data: parts } = useParts();
  const { data: options } = useFilterOptions();

  /** Writes a patch into the URL. Any change but paging returns to page one -
   *  staying on page 34 of a filter that now has two rows shows an empty table
   *  that looks like a bug. */
  const update = (patch: Record<string, string | string[] | null>, keepOffset = false) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      next.delete(key);
      if (value === null || value === "") continue;
      for (const item of Array.isArray(value) ? value : [value]) {
        if (item !== "") next.append(key, item);
      }
    }
    if (!keepOffset) next.delete("offset");
    setParams(next, { replace: true });
  };

  const sharedFilters = {
    tier: tiers.length ? tiers : undefined,
    customer_id: customerIds.length ? customerIds : undefined,
    region: regions.length ? regions : undefined,
    model: models.length ? models : undefined,
    search: search || undefined,
  };

  const predictionFilters = {
    ...sharedFilters,
    part_code: partCodes.length ? partCodes : undefined,
    max_rul_days: maxRul === null || maxRul === "" ? undefined : Number(maxRul),
    escalated_only: escalatedOnly || undefined,
    sort: sort.key as "probability" | "rul" | "vin" | "cost" | "health",
    order: sort.order,
    limit: PAGE_SIZE,
    offset,
  };

  const vehicleFilters = {
    ...sharedFilters,
    sort: (["vin", "probability", "rul", "cost", "km", "model"].includes(sort.key)
      ? sort.key
      : "probability") as "vin" | "probability" | "rul" | "cost" | "km" | "model",
    order: sort.order,
    limit: PAGE_SIZE,
    offset,
  };

  const predictions = usePredictions(predictionFilters);
  const vehicles = useVehicles(vehicleFilters);
  const active = mode === "components" ? predictions : vehicles;

  const componentColumns: Column<PredictionOut>[] = [
    {
      id: "vin",
      header: "VIN",
      width: "minmax(11rem, 1.1fr)",
      sortKey: "vin",
      alwaysVisible: true,
      cell: (row) => <span className="font-medium text-ink">{row.vin}</span>,
    },
    {
      id: "component",
      header: "Component",
      width: "minmax(9rem, 1fr)",
      alwaysVisible: true,
      cell: (row) => row.part_name,
    },
    {
      id: "customer",
      header: "Customer",
      width: "minmax(9rem, 1fr)",
      cell: (row) => <span className="text-muted">{row.customer_name}</span>,
    },
    {
      id: "model",
      header: "Model",
      width: "minmax(8rem, 0.9fr)",
      cell: (row) => (
        <span className="text-muted">
          {row.model} <span className="text-faint">{row.variant}</span>
        </span>
      ),
    },
    {
      id: "region",
      header: "Region",
      width: "6.5rem",
      defaultHidden: true,
      cell: (row) => <span className="text-muted">{row.region}</span>,
    },
    {
      id: "tier",
      header: "Risk",
      width: "8.5rem",
      cell: (row) => (
        <RiskBadge
          tier={row.risk_tier}
          escalated={row.escalated}
          title={row.escalation_reason ?? undefined}
        />
      ),
    },
    {
      id: "probability",
      header: "Probability",
      width: "7rem",
      align: "right",
      sortKey: "probability",
      cell: (row) => (
        <span className={cn(tierStyle(row.risk_tier).text, "font-medium")}>
          {formatPercent(row.failure_probability)}
        </span>
      ),
    },
    {
      id: "health",
      header: "Health",
      width: "6rem",
      align: "right",
      sortKey: "health",
      defaultHidden: true,
      cell: (row) => row.health_index.toFixed(0),
    },
    {
      id: "rul",
      header: "Life left",
      width: "7.5rem",
      align: "right",
      sortKey: "rul",
      cell: (row) => (
        <span className={row.rul_days <= 0 ? "text-risk-red" : undefined}>
          {formatRulDays(row.rul_days)}
        </span>
      ),
    },
    {
      id: "signal",
      header: "Top signal",
      width: "minmax(9rem, 0.9fr)",
      defaultHidden: true,
      cell: (row) =>
        row.top_signal ? (
          <span className="text-muted">
            {row.top_signal}{" "}
            <span className="text-faint">
              {formatPercent(row.top_signal_share, { alreadyScaled: true })}
            </span>
          </span>
        ) : (
          <span className="text-faint">-</span>
        ),
    },
    {
      id: "cost",
      header: "Exposure",
      width: "7.5rem",
      align: "right",
      sortKey: "cost",
      cell: (row) => formatCurrency(row.estimated_cost_impact),
    },
  ];

  const vehicleColumns: Column<VehicleOut>[] = [
    {
      id: "vin",
      header: "VIN",
      width: "minmax(11rem, 1.1fr)",
      sortKey: "vin",
      alwaysVisible: true,
      cell: (row) => <span className="font-medium text-ink">{row.vin}</span>,
    },
    {
      id: "customer",
      header: "Customer",
      width: "minmax(9rem, 1fr)",
      cell: (row) => <span className="text-muted">{row.customer_name}</span>,
    },
    {
      id: "model",
      header: "Model",
      width: "minmax(8rem, 1fr)",
      sortKey: "model",
      cell: (row) => (
        <span className="text-muted">
          {row.model} <span className="text-faint">{row.variant}</span>
        </span>
      ),
    },
    {
      id: "region",
      header: "Region",
      width: "6.5rem",
      cell: (row) => <span className="text-muted">{row.region}</span>,
    },
    {
      id: "worst",
      header: "Worst component",
      width: "minmax(9rem, 1fr)",
      cell: (row) =>
        row.worst_part_name ?? <span className="text-faint">Nothing scored</span>,
    },
    {
      id: "tier",
      header: "Risk",
      width: "8.5rem",
      cell: (row) => <RiskBadge tier={row.risk_tier} />,
    },
    {
      id: "probability",
      header: "Probability",
      width: "7rem",
      align: "right",
      sortKey: "probability",
      cell: (row) =>
        row.worst_probability === undefined ? (
          <span className="text-faint">-</span>
        ) : (
          <span className={cn(tierStyle(row.risk_tier).text, "font-medium")}>
            {formatPercent(row.worst_probability)}
          </span>
        ),
    },
    {
      id: "rul",
      header: "Life left",
      width: "7.5rem",
      align: "right",
      sortKey: "rul",
      cell: (row) =>
        row.min_rul_days === undefined ? (
          <span className="text-faint">-</span>
        ) : (
          <span className={row.min_rul_days <= 0 ? "text-risk-red" : undefined}>
            {formatRulDays(row.min_rul_days)}
          </span>
        ),
    },
    {
      id: "red",
      header: "Red parts",
      width: "6rem",
      align: "right",
      cell: (row) => formatNumber(row.red_count ?? 0),
    },
    {
      id: "km",
      header: "Odometer",
      width: "8rem",
      align: "right",
      sortKey: "km",
      defaultHidden: true,
      cell: (row) => formatKm(row.total_km_driven),
    },
    {
      id: "cost",
      header: "Exposure",
      width: "7.5rem",
      align: "right",
      sortKey: "cost",
      cell: (row) => formatCurrency(row.cost_exposure ?? 0),
    },
  ];

  const columns = (mode === "components" ? componentColumns : vehicleColumns) as Column<
    PredictionOut | VehicleOut
  >[];

  const visibleColumnIds = useMemo(
    () =>
      columns
        .filter((column) => !column.defaultHidden && !hiddenColumns.includes(column.id))
        .map((column) => column.id)
        .concat(hiddenColumns.filter((id) => columns.some((column) => column.id === id && column.defaultHidden))),
    // Hidden ids double as "shown" for columns that start hidden, so the menu
    // is one list of toggles rather than two lists with opposite meanings.
    [columns, hiddenColumns],
  );

  const appliedFilters = [
    ...tiers.map((tier) => ({
      id: `tier-${tier}`,
      label: `${tierStyle(tier).label} tier`,
      onRemove: () => update({ tier: tiers.filter((item) => item !== tier) }),
    })),
    ...customerIds.map((id) => ({
      id: `customer-${id}`,
      label: customers?.find((customer) => customer.customer_id === id)?.name ?? `Customer ${id}`,
      onRemove: () =>
        update({ customer: customerIds.filter((item) => item !== id).map(String) }),
    })),
    ...regions.map((region) => ({
      id: `region-${region}`,
      label: region,
      onRemove: () => update({ region: regions.filter((item) => item !== region) }),
    })),
    ...models.map((model) => ({
      id: `model-${model}`,
      label: model,
      onRemove: () => update({ model: models.filter((item) => item !== model) }),
    })),
    ...partCodes.map((code) => ({
      id: `part-${code}`,
      label: parts?.find((part) => part.part_code === code)?.part_name ?? code,
      onRemove: () => update({ part: partCodes.filter((item) => item !== code) }),
    })),
    ...(maxRul !== null && maxRul !== ""
      ? [
          {
            id: "max-rul",
            label: Number(maxRul) <= 0 ? "Overdue" : `Inside ${maxRul} days`,
            onRemove: () => update({ max_rul: null }),
          },
        ]
      : []),
    ...(escalatedOnly
      ? [
          {
            id: "escalated",
            label: "Escalated on life",
            onRemove: () => update({ escalated: null }),
          },
        ]
      : []),
  ];

  const activeSavedView = SAVED_VIEWS.find(
    (view) =>
      (view.params.tier === "" ? tiers.length === 0 : tiers.length === 1 && tiers[0] === view.params.tier) &&
      (view.params.max_rul === "" ? maxRul === null : maxRul === view.params.max_rul) &&
      (view.params.escalated === "" ? !escalatedOnly : escalatedOnly),
  );

  const applySavedView = (view: (typeof SAVED_VIEWS)[number]) => {
    const isActive = activeSavedView?.id === view.id;
    update({
      view: "components",
      tier: isActive ? null : view.params.tier || null,
      max_rul: isActive ? null : view.params.max_rul || null,
      escalated: isActive ? null : view.params.escalated || null,
    });
  };

  const runExport = async () => {
    setExporting(true);
    try {
      const blob = await exportPredictionsCsv({
        tier: tiers.length ? tiers : undefined,
        customer_id: customerIds.length ? customerIds : undefined,
        region: regions.length ? regions : undefined,
        model: models.length ? models : undefined,
        part_code: partCodes.length ? partCodes : undefined,
        search: search || undefined,
        sort: predictionFilters.sort,
        order: sort.order,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `fleetguard-predictions-${new Date().toISOString().slice(0, 10)}.csv`;
      link.click();
      URL.revokeObjectURL(url);
      toast.show({
        tone: "success",
        title: "Export downloaded",
        detail: "Every component matching the current filters, not just this page.",
      });
    } catch (error) {
      toast.show({
        tone: "error",
        title: "Export failed",
        detail: error instanceof Error ? error.message : "The server did not return the file.",
      });
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Fleet"
        description={
          mode === "components"
            ? "Every scored component, ranked by how likely it is to fail. Open a row for the evidence behind it."
            : "Every monitored vehicle, showing the component closest to failing."
        }
        actions={
          <>
            <Menu
              label="Columns"
              width="w-56"
              trigger={
                <Button icon={SlidersHorizontal} size="sm">
                  Columns
                </Button>
              }
            >
              {() => (
                <>
                  <MenuLabel>Show columns</MenuLabel>
                  {columns
                    .filter((column) => !column.alwaysVisible)
                    .map((column) => {
                      const shown = visibleColumnIds.includes(column.id);
                      return (
                        <MenuItem
                          key={column.id}
                          selected={shown}
                          onClick={() =>
                            setHiddenColumns((current) =>
                              current.includes(column.id)
                                ? current.filter((id) => id !== column.id)
                                : [...current, column.id],
                            )
                          }
                        >
                          <span className="flex-1 truncate">{column.header}</span>
                          <span className="text-[0.6875rem] text-faint">
                            {shown ? "Shown" : "Hidden"}
                          </span>
                        </MenuItem>
                      );
                    })}
                </>
              )}
            </Menu>

            <Button icon={Download} size="sm" onClick={runExport} loading={exporting}>
              Export CSV
            </Button>
          </>
        }
      />

      <Card className="mb-4 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border border-hairline p-0.5">
            <ModeButton
              active={mode === "components"}
              onClick={() => update({ view: null })}
              icon={Layers}
              label="By component"
            />
            <ModeButton
              active={mode === "vehicles"}
              onClick={() => update({ view: "vehicles" })}
              icon={Truck}
              label="By vehicle"
            />
          </div>

          <SearchInput
            value={search}
            onValueChange={(value) => update({ q: value || null })}
            placeholder="VIN, model, region, customer or component"
            className="min-w-[16rem] flex-1"
          />

          <FilterMenu
            label="Tier"
            options={TIER_ORDER.map((tier) => ({ value: tier, label: tierStyle(tier).label }))}
            selected={tiers}
            onChange={(next) => update({ tier: next })}
          />
          <FilterMenu
            label="Customer"
            options={(customers ?? []).map((customer) => ({
              value: customer.customer_id,
              label: customer.name,
              meta: formatNumber(customer.vehicle_count ?? 0),
            }))}
            selected={customerIds}
            onChange={(next) => update({ customer: next.map(String) })}
          />
          <FilterMenu
            label="Region"
            options={(options?.regions ?? []).map((region) => ({ value: region, label: region }))}
            selected={regions}
            onChange={(next) => update({ region: next })}
          />
          <FilterMenu
            label="Model"
            options={(options?.models ?? []).map((model) => ({ value: model, label: model }))}
            selected={models}
            onChange={(next) => update({ model: next })}
          />
          {mode === "components" ? (
            <FilterMenu
              label="Component"
              options={(parts ?? []).map((part) => ({
                value: part.part_code,
                label: part.part_name,
              }))}
              selected={partCodes}
              onChange={(next) => update({ part: next })}
            />
          ) : null}
        </div>

        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className="mr-0.5 text-[0.75rem] text-faint">Saved views</span>
          {SAVED_VIEWS.map((view) => (
            <button
              key={view.id}
              type="button"
              title={view.hint}
              onClick={() => applySavedView(view)}
              aria-pressed={activeSavedView?.id === view.id}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-[0.75rem] transition-colors",
                activeSavedView?.id === view.id
                  ? "border-accent/40 bg-accent-soft text-accent-ink"
                  : "border-hairline bg-surface text-muted hover:text-ink",
              )}
            >
              {view.label}
            </button>
          ))}
        </div>

        <AppliedFilters
          className="mt-2.5"
          filters={appliedFilters}
          onClearAll={() =>
            update({
              tier: null,
              customer: null,
              region: null,
              model: null,
              part: null,
              max_rul: null,
              escalated: null,
              q: null,
            })
          }
        />
      </Card>

      {active.isError ? (
        <Card>
          <ErrorState error={active.error} onRetry={() => void active.refetch()} />
        </Card>
      ) : (
        <>
          <DataTable
            label={mode === "components" ? "Fleet components" : "Fleet vehicles"}
            columns={columns}
            rows={(active.data?.items ?? []) as (PredictionOut | VehicleOut)[]}
            getRowId={(row) =>
              "part_code" in row ? `${row.vin}-${row.part_code}` : row.vin
            }
            visibleColumnIds={visibleColumnIds}
            sort={sort}
            onSortChange={(next) => update({ sort: next.key, order: next.order })}
            loading={active.isPending}
            virtualized
            minWidth="76rem"
            height={Math.min(
              620,
              Math.max(240, (active.data?.items.length ?? 8) * 52 + 8),
            )}
            activeRowId={
              selected ? `${selected.vin}-${selected.partCode}` : null
            }
            onRowClick={(row) => {
              const partCode =
                "part_code" in row ? row.part_code : (row.worst_part_code ?? null);
              if (!partCode) return;
              setSelected({ vin: row.vin, partCode });
            }}
            empty={
              <EmptyState
                icon={Filter}
                title="Nothing matches these filters"
                description={
                  appliedFilters.length > 0 || search
                    ? "No component in this scope matches every filter applied. Removing one usually brings the list back."
                    : "This scope has no scored components yet. Run the scoring job, or switch scope."
                }
                action={
                  appliedFilters.length > 0 || search ? (
                    <Button
                      onClick={() =>
                        update({
                          tier: null,
                          customer: null,
                          region: null,
                          model: null,
                          part: null,
                          max_rul: null,
                          escalated: null,
                          q: null,
                        })
                      }
                    >
                      Clear filters
                    </Button>
                  ) : null
                }
              />
            }
          />

          <Pagination
            className="mt-3"
            total={active.data?.total ?? 0}
            limit={PAGE_SIZE}
            offset={offset}
            noun={mode === "components" ? "components" : "vehicles"}
            onOffsetChange={(next) => update({ offset: String(next) }, true)}
          />
        </>
      )}

      <PredictionDrawer
        vin={selected?.vin ?? null}
        partCode={selected?.partCode ?? null}
        onClose={() => setSelected(null)}
      />
    </>
  );
}

function ModeButton({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof Layers;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[0.8125rem] transition-colors",
        active ? "bg-accent-soft font-medium text-accent-ink" : "text-muted hover:text-ink",
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {label}
    </button>
  );
}
