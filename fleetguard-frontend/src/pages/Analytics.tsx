/**
 * Analytics - where the money is going and who is doing better than whom.
 *
 * Two deliberate choices about honesty here. Cost exposure is a **snapshot**,
 * not a time series: the API scores the fleet as it stands today, and drawing
 * exposure "over time" would mean inventing history the product does not have.
 * And failure trends are drawn as small multiples, one panel per component on
 * a shared scale, rather than eight coloured lines in one frame - eight
 * colours is a legend to decode, eight panels is a shape to compare.
 */

import { Layers, MapPin, TrendingUp, Users } from "lucide-react";
import { useState } from "react";
import { Area, AreaChart, YAxis } from "recharts";

import {
  useCostExposure,
  useFailureTrends,
  useFleetComparison,
  useOverview,
} from "@/api/queries";
import type { ComponentTrendPoint, FleetComparisonRow } from "@/api/types";
import { ExposureBars, SignalWeightBars } from "@/components/charts/FleetCharts";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ChartContainer, useChartAnimation, CHART_COLORS } from "@/components/ui/Chart";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { KpiTile } from "@/components/ui/KpiTile";
import { SkeletonCard, SkeletonTable } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";
import {
  formatCurrency,
  formatDecimal,
  formatMonth,
  formatNumber,
  formatPercent,
} from "@/lib/format";

type Dimension = "customer" | "component" | "region";

const DIMENSIONS: { value: Dimension; label: string; icon: typeof Users }[] = [
  { value: "customer", label: "By customer", icon: Users },
  { value: "component", label: "By component", icon: Layers },
  { value: "region", label: "By region", icon: MapPin },
];

export default function AnalyticsPage() {
  const [dimension, setDimension] = useState<Dimension>("customer");

  const overview = useOverview();
  const exposure = useCostExposure(dimension);
  const trends = useFailureTrends(12);
  const comparison = useFleetComparison();

  const kpis = overview.data?.kpis;

  return (
    <>
      <PageHeader
        title="Analytics"
        description="Cost exposure, failure trends and how each operator compares to the fleet. Exposure is what today's predictions are worth if every component runs to failure."
      />

      {overview.isPending || !kpis || !comparison.data ? (
        <SkeletonCard height="h-20" />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KpiTile
            label="Cost exposure"
            value={kpis.total_cost_exposure}
            format={(value) => formatCurrency(value)}
            hint="Probability-weighted across every scored component"
          />
          <KpiTile
            label="Avoidable by acting now"
            value={kpis.avoidable_cost}
            tone="green"
            format={(value) => formatCurrency(value)}
            hint="Gross saving on the red components if each is replaced on plan"
          />
          <KpiTile
            label="Fleet mean health"
            value={comparison.data.fleet_mean_health_index}
            format={(value) => value.toFixed(1)}
            hint="Health index across every scored component"
          />
          <KpiTile
            label="Failures per 100 vehicles"
            value={comparison.data.fleet_failures_per_100_vehicles}
            format={(value) => formatDecimal(value, 1)}
            hint="Unplanned failures in the last twelve months"
          />
        </div>
      )}

      <Card className="mt-4">
        <CardHeader
          title="Cost exposure"
          description="Two measures side by side: probability-weighted exposure across every scored component, and the gross saving available on the red ones. A snapshot of today's predictions, not a history."
          action={
            <div className="flex rounded-lg border border-hairline p-0.5">
              {DIMENSIONS.map((entry) => (
                <button
                  key={entry.value}
                  type="button"
                  onClick={() => setDimension(entry.value)}
                  aria-pressed={dimension === entry.value}
                  className={cn(
                    "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[0.8125rem] transition-colors",
                    dimension === entry.value
                      ? "bg-accent-soft font-medium text-accent-ink"
                      : "text-muted hover:text-ink",
                  )}
                >
                  <entry.icon className="h-3.5 w-3.5" aria-hidden="true" />
                  {entry.label}
                </button>
              ))}
            </div>
          }
        />
        <CardBody>
          {exposure.isError ? (
            <ErrorState error={exposure.error} onRetry={() => void exposure.refetch()} compact />
          ) : exposure.isPending || !exposure.data ? (
            <SkeletonCard height="h-64" className="border-0 p-0" />
          ) : exposure.data.rows.length === 0 ? (
            <EmptyState
              compact
              title="No exposure to break down"
              description="Nothing in this scope has been scored yet, so there is no cost to attribute."
            />
          ) : (
            <>
              <ExposureBars
                height={Math.max(220, exposure.data.rows.length * 38)}
                rows={exposure.data.rows.map((row) => ({
                  label: row.label,
                  exposure: row.exposure,
                  avoidable: row.avoidable,
                  meta: [
                    { label: "Red components", value: formatNumber(row.red_count) },
                    { label: "Components", value: formatNumber(row.components) },
                  ],
                }))}
              />
              <p className="mt-3 text-[0.75rem] leading-5 text-muted">
                {formatCurrency(exposure.data.total_exposure, { compact: false })} of expected
                exposure across every scored component.{" "}
                <span className="text-risk-green">
                  {formatCurrency(exposure.data.total_avoidable, { compact: false })}
                </span>{" "}
                of that is avoidable today by replacing the red components on plan instead of
                after a roadside failure - a different population, which is why the two bars are
                drawn side by side rather than one inside the other.
              </p>
            </>
          )}
        </CardBody>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Failures by component"
            description="Twelve months per component, on one shared scale. The tallest panel is the component costing the most workshop time."
          />
          <CardBody>
            {trends.isPending || !trends.data ? (
              <SkeletonCard height="h-64" className="border-0 p-0" />
            ) : trends.data.by_component.length === 0 ? (
              <EmptyState
                compact
                icon={TrendingUp}
                title="No failures on record"
                description="Component trends appear once job cards exist in this scope."
              />
            ) : (
              <ComponentTrendGrid points={trends.data.by_component} months={trends.data.months} />
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Signal prevalence"
            description="How much of the fleet's risk each telematics signal carries, averaged across every deployed rule."
          />
          <CardBody>
            {trends.isPending || !trends.data ? (
              <SkeletonCard height="h-64" className="border-0 p-0" />
            ) : (
              <SignalWeightBars signals={trends.data.signal_prevalence} height={300} />
            )}
          </CardBody>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader
          title="Customer benchmarking"
          description="Each operator against the fleet mean. Failures per 100 vehicles is the honest comparison - a big fleet has more failures without being worse run."
        />
        <CardBody className="px-0 pb-0">
          {comparison.isError ? (
            <ErrorState
              error={comparison.error}
              onRetry={() => void comparison.refetch()}
              compact
            />
          ) : comparison.isPending || !comparison.data ? (
            <SkeletonTable rows={5} columns={7} className="rounded-none border-x-0 border-b-0" />
          ) : (
            <BenchmarkTable
              rows={comparison.data.rows}
              fleetFailureRate={comparison.data.fleet_failures_per_100_vehicles}
              fleetHealth={comparison.data.fleet_mean_health_index}
            />
          )}
        </CardBody>
      </Card>
    </>
  );
}

/** One sparkline per component, all sharing a y-axis so the panels compare. */
function ComponentTrendGrid({
  points,
  months,
}: {
  points: ComponentTrendPoint[];
  months: string[];
}) {
  const animate = useChartAnimation();

  const byComponent = new Map<string, { name: string; series: { month: string; failures: number }[] }>();
  for (const point of points) {
    const entry = byComponent.get(point.part_code) ?? { name: point.part_name, series: [] };
    entry.series.push({ month: point.month, failures: point.failures });
    byComponent.set(point.part_code, entry);
  }

  const panels = [...byComponent.entries()]
    .map(([code, entry]) => {
      // Months with no failures are absent from the response; a gap in a trend
      // line would read as missing data rather than as a quiet month.
      const series = months.map((month) => ({
        month,
        failures: entry.series.find((row) => row.month === month)?.failures ?? 0,
      }));
      return {
        code,
        name: entry.name,
        series,
        total: series.reduce((sum, row) => sum + row.failures, 0),
      };
    })
    .sort((a, b) => b.total - a.total);

  const peak = Math.max(...panels.flatMap((panel) => panel.series.map((row) => row.failures)), 1);

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {panels.map((panel) => (
        <div key={panel.code} className="rounded-card border border-hairline px-3 pb-1 pt-2.5">
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-[0.8125rem] text-ink">{panel.name}</span>
            <span className="tabular shrink-0 text-[0.75rem] text-muted">
              {formatNumber(panel.total)} in 12 months
            </span>
          </div>
          <ChartContainer height={64}>
            <AreaChart data={panel.series} margin={{ top: 6, right: 0, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id={`spark-${panel.code}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgb(var(--accent))" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="rgb(var(--accent))" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <YAxis domain={[0, peak]} hide />
              <Area
                type="monotone"
                dataKey="failures"
                stroke={CHART_COLORS.accent}
                strokeWidth={1.5}
                fill={`url(#spark-${panel.code})`}
                isAnimationActive={animate}
              />
            </AreaChart>
          </ChartContainer>
          <p className="pb-1 text-[0.6875rem] text-faint">
            {formatMonth(panel.series[0]?.month ?? "")} to{" "}
            {formatMonth(panel.series.at(-1)?.month ?? "")}
          </p>
        </div>
      ))}
    </div>
  );
}

function BenchmarkTable({
  rows,
  fleetFailureRate,
  fleetHealth,
}: {
  rows: FleetComparisonRow[];
  fleetFailureRate: number;
  fleetHealth: number;
}) {
  const columns: Column<FleetComparisonRow>[] = [
    {
      id: "customer",
      header: "Customer",
      width: "minmax(11rem, 1.2fr)",
      cell: (row) => (
        <span>
          <span className="font-medium text-ink">{row.customer_name}</span>{" "}
          <span className="text-faint">{row.region}</span>
        </span>
      ),
    },
    {
      id: "contract",
      header: "Contract",
      width: "7rem",
      cell: (row) => <span className="text-muted">{row.contract_tier}</span>,
    },
    {
      id: "vehicles",
      header: "Vehicles",
      width: "6.5rem",
      align: "right",
      cell: (row) => formatNumber(row.vehicles),
    },
    {
      id: "rate",
      header: "Failures / 100",
      width: "9rem",
      align: "right",
      cell: (row) => (
        <span className="inline-flex items-center gap-1.5">
          {formatDecimal(row.failures_per_100_vehicles, 1)}
          <Delta
            value={row.failures_per_100_vehicles - fleetFailureRate}
            goodWhenLower
            format={(value) => formatDecimal(Math.abs(value), 1)}
          />
        </span>
      ),
    },
    {
      id: "health",
      header: "Mean health",
      width: "9rem",
      align: "right",
      cell: (row) => (
        <span className="inline-flex items-center gap-1.5">
          {row.mean_health_index.toFixed(1)}
          <Delta
            value={row.mean_health_index - fleetHealth}
            format={(value) => Math.abs(value).toFixed(1)}
          />
        </span>
      ),
    },
    {
      id: "red",
      header: "Red share",
      width: "7rem",
      align: "right",
      cell: (row) => formatPercent(row.red_share),
    },
    {
      id: "km",
      header: "Km / day",
      width: "7rem",
      align: "right",
      cell: (row) => formatNumber(Math.round(row.mean_km_per_day)),
    },
    {
      id: "exposure",
      header: "Exposure",
      width: "7.5rem",
      align: "right",
      cell: (row) => formatCurrency(row.cost_exposure),
    },
    {
      id: "perVehicle",
      header: "Per vehicle",
      width: "7.5rem",
      align: "right",
      cell: (row) => formatCurrency(row.exposure_per_vehicle, { compact: false }),
    },
  ];

  return (
    <DataTable
      label="Customer benchmarking"
      columns={columns}
      rows={rows}
      getRowId={(row) => String(row.customer_id)}
      minWidth="76rem"
      className="rounded-none border-x-0 border-b-0"
      empty={
        <EmptyState
          compact
          title="Only one customer in this view"
          description="Benchmarking compares operators against each other, so it needs the manufacturer view."
        />
      }
    />
  );
}

/** A signed difference from the fleet mean, coloured by whether it is good. */
function Delta({
  value,
  goodWhenLower = false,
  format,
}: {
  value: number;
  goodWhenLower?: boolean;
  format: (value: number) => string;
}) {
  if (Math.abs(value) < 0.05) {
    return <span className="text-[0.6875rem] text-faint">at fleet mean</span>;
  }
  const better = goodWhenLower ? value < 0 : value > 0;
  return (
    <span
      className={cn(
        "text-[0.6875rem]",
        // Not a risk tier: this is a comparison, so it uses the neutral accent
        // for better and the muted tone for worse rather than green and red.
        better ? "text-accent" : "text-muted",
      )}
      title={better ? "Better than the fleet mean" : "Worse than the fleet mean"}
    >
      {value > 0 ? "+" : "-"}
      {format(value)}
    </span>
  );
}
