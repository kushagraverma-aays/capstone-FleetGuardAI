/**
 * RUL Explorer - what to replace, in the order it has to be replaced.
 *
 * Overdue is a band of its own at the top, not the first entries of a sorted
 * list. Hundreds of components read "0 days" in this fleet, and a flat list
 * opening with a column of zeros looks like a broken screen rather than an
 * urgent one. Separating them also puts the genuinely actionable band -
 * inside 30 days, long enough to order the part and book the slot - where the
 * eye lands second.
 *
 * The band counts come from `GET /api/rul/bands`, computed across the whole
 * scope rather than the loaded page, so the tab labels do not change as
 * someone pages through.
 */

import { CalendarClock, Filter } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useCustomers, useParts, useRul, useRulBands } from "@/api/queries";
import type { RiskTier, RulRow, UrgencyBand } from "@/api/types";
import { PredictionDrawer } from "@/components/fleet/PredictionDrawer";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { FilterMenu } from "@/components/ui/FilterMenu";
import { SearchInput } from "@/components/ui/Input";
import { Pagination } from "@/components/ui/Pagination";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { cn } from "@/lib/cn";
import { formatCurrency, formatKm, formatNumber, formatPercent, formatRulDays } from "@/lib/format";
import { BAND_ORDER, BAND_STYLES, TIER_ORDER, tierStyle } from "@/lib/risk";

const PAGE_SIZE = 50;

export default function RulExplorerPage() {
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState<{ vin: string; partCode: string } | null>(null);

  const band = (params.get("band") ?? "overdue") as UrgencyBand;
  const search = params.get("q") ?? "";
  const offset = Number.parseInt(params.get("offset") ?? "0", 10) || 0;
  const tiers = params.getAll("tier") as RiskTier[];
  const customerIds = params.getAll("customer").map(Number).filter(Number.isFinite);
  const partCodes = params.getAll("part");

  const { data: customers } = useCustomers();
  const { data: parts } = useParts();

  const update = (patch: Record<string, string | string[] | null>, keepOffset = false) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      next.delete(key);
      if (value === null || value === "") continue;
      for (const item of Array.isArray(value) ? value : [value]) next.append(key, item);
    }
    if (!keepOffset) next.delete("offset");
    setParams(next, { replace: true });
  };

  const filters = {
    tier: tiers.length ? tiers : undefined,
    customer_id: customerIds.length ? customerIds : undefined,
    part_code: partCodes.length ? partCodes : undefined,
    search: search || undefined,
  };

  const bands = useRulBands(filters);
  const rows = useRul({ ...filters, band, limit: PAGE_SIZE, offset });

  const columns: Column<RulRow>[] = [
    {
      id: "vin",
      header: "VIN",
      width: "minmax(11rem, 1fr)",
      cell: (row) => <span className="font-medium text-ink">{row.vin}</span>,
    },
    {
      id: "component",
      header: "Component",
      width: "minmax(9rem, 1fr)",
      cell: (row) => row.part_name,
    },
    {
      id: "customer",
      header: "Customer",
      width: "minmax(9rem, 1fr)",
      cell: (row) => <span className="text-muted">{row.customer_name}</span>,
    },
    {
      id: "rul",
      header: "Life left",
      width: "8rem",
      align: "right",
      cell: (row) => (
        <span className={cn("font-medium", row.rul_days <= 0 ? "text-risk-red" : "text-ink")}>
          {formatRulDays(row.rul_days)}
        </span>
      ),
    },
    {
      id: "window",
      header: "Window",
      width: "8rem",
      align: "right",
      cell: (row) => (
        <span className="text-muted">
          {row.window_from_days}-{row.window_to_days} d
        </span>
      ),
    },
    {
      id: "distance",
      header: "Distance left",
      width: "8rem",
      align: "right",
      cell: (row) => formatKm(row.rul_km),
    },
    {
      id: "lead",
      header: "Lead time",
      width: "7rem",
      align: "right",
      cell: (row) => (
        <span
          className={cn(
            row.rul_days > 0 && row.rul_days < row.lead_time_days ? "text-risk-amber" : undefined,
          )}
          title={
            row.rul_days > 0 && row.rul_days < row.lead_time_days
              ? "The part takes longer to arrive than the component has left"
              : undefined
          }
        >
          {formatNumber(row.lead_time_days)} d
        </span>
      ),
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
      cell: (row) => (
        <span className={tierStyle(row.risk_tier).text}>
          {formatPercent(row.failure_probability)}
        </span>
      ),
    },
    {
      id: "cost",
      header: "Exposure",
      width: "7.5rem",
      align: "right",
      cell: (row) => formatCurrency(row.estimated_cost_impact),
    },
  ];

  const bandStyle = BAND_STYLES[band] ?? BAND_STYLES.healthy;

  return (
    <>
      <PageHeader
        title="RUL Explorer"
        description="Components ranked by how much useful life is left. Overdue is separated from what is still plannable, because they are different jobs."
      />

      {/* Bands as tabs: the counts are the whole-scope totals, so switching
          band never changes them. */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {BAND_ORDER.map((entry) => {
          const style = BAND_STYLES[entry];
          const count = bands.data?.[entry];
          const active = entry === band;
          return (
            <button
              key={entry}
              type="button"
              onClick={() => update({ band: entry })}
              aria-pressed={active}
              className={cn(
                "rounded-card border p-4 text-left transition-colors",
                active ? "border-accent/40 bg-accent-soft/50" : "border-hairline bg-surface hover:bg-canvas",
              )}
            >
              <p className={cn("text-label font-medium uppercase tracking-wider", style.text)}>
                {style.label}
              </p>
              <p className="tabular mt-1.5 text-[1.75rem] font-semibold leading-none text-ink">
                {bands.isPending ? "-" : formatNumber(count ?? 0)}
              </p>
              <p className="mt-1.5 text-[0.75rem] leading-4 text-muted">{style.description}</p>
            </button>
          );
        })}
      </div>

      <Card className="my-4 p-3">
        <div className="flex flex-wrap items-center gap-2">
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
            }))}
            selected={customerIds}
            onChange={(next) => update({ customer: next.map(String) })}
          />
          <FilterMenu
            label="Component"
            options={(parts ?? []).map((part) => ({
              value: part.part_code,
              label: part.part_name,
            }))}
            selected={partCodes}
            onChange={(next) => update({ part: next })}
          />
        </div>
      </Card>

      <div className="mb-2 flex items-baseline justify-between gap-4">
        <h2 className="text-[0.9375rem] font-medium text-ink">
          {bandStyle.label}
          <span className="ml-2 text-[0.8125rem] font-normal text-muted">
            {bandStyle.description}
          </span>
        </h2>
      </div>

      {rows.isError ? (
        <Card>
          <ErrorState error={rows.error} onRetry={() => void rows.refetch()} />
        </Card>
      ) : (
        <>
          <DataTable
            label={`Components ${bandStyle.label.toLowerCase()}`}
            columns={columns}
            rows={rows.data?.items ?? []}
            getRowId={(row) => `${row.vin}-${row.part_code}`}
            loading={rows.isPending}
            virtualized
            minWidth="82rem"
            height={Math.min(600, Math.max(240, (rows.data?.items.length ?? 8) * 52 + 8))}
            activeRowId={selected ? `${selected.vin}-${selected.partCode}` : null}
            onRowClick={(row) => setSelected({ vin: row.vin, partCode: row.part_code })}
            empty={
              <EmptyState
                icon={band === "overdue" ? CalendarClock : Filter}
                title={
                  band === "overdue"
                    ? "Nothing is overdue in this view"
                    : "Nothing in this band"
                }
                description={
                  band === "overdue"
                    ? "Every component still has projected life left. The other bands show what is coming."
                    : "No component in this scope falls in this band with the filters applied."
                }
                action={
                  band === "overdue" ? (
                    <Button onClick={() => update({ band: "within_30_days" })}>
                      Show what is inside 30 days
                    </Button>
                  ) : null
                }
              />
            }
          />

          <Pagination
            className="mt-3"
            total={rows.data?.total ?? 0}
            limit={PAGE_SIZE}
            offset={offset}
            noun="components"
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
