/**
 * Command Centre - what the fleet looks like today.
 *
 * The order is deliberate: four numbers a manager can quote, then the shape of
 * the risk, then what to do about it before lunch. The "needs attention" list
 * is last on the page but first in importance, so it is the widest thing on
 * screen and every row is a link into the work.
 *
 * Everything on this screen comes from a single `GET /api/overview`, which is
 * already scoped, so nothing here re-filters or re-totals anything.
 */

import { AlertTriangle, ArrowRight, Timer, TrendingDown, Truck, Wallet } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { useCostExposure, useOverview, useScopeInfo } from "@/api/queries";
import type { AttentionRow } from "@/api/types";
import { ExposureBars, FailureTrendChart, SignalWeightBars, TierDonut } from "@/components/charts/FleetCharts";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { KpiTile } from "@/components/ui/KpiTile";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { SkeletonCard, SkeletonKpiRow, SkeletonTable } from "@/components/ui/Skeleton";
import {
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
  formatRulDays,
} from "@/lib/format";

/** True when a month bucket is the one we are currently living in - its
 *  counts are partial, and a line that dives at the right-hand edge otherwise
 *  reads as a sudden improvement. */
function isPartialMonth(month: string | undefined): boolean {
  if (!month) return false;
  const now = new Date();
  const current = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  return month === current;
}

export default function CommandCentrePage() {
  const overview = useOverview();
  const { data: scopeInfo } = useScopeInfo();
  const navigate = useNavigate();

  // In a single-customer view "exposure by customer" is one bar, which tells
  // nobody anything. The same slot answers the question that view actually
  // has: which components are carrying the cost.
  const isSingleCustomer = scopeInfo?.is_manufacturer === false;
  const componentExposure = useCostExposure("component");

  const kpis = overview.data?.kpis;

  const attentionColumns: Column<AttentionRow>[] = [
    {
      id: "vin",
      header: "Vehicle",
      width: "minmax(11rem, 1.2fr)",
      cell: (row) => (
        <span className="font-medium text-ink">{row.vin}</span>
      ),
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
      cell: (row) => formatPercent(row.failure_probability),
    },
    {
      id: "rul",
      header: "Life left",
      width: "7.5rem",
      align: "right",
      cell: (row) => (
        <span className={row.rul_days <= 0 ? "text-risk-red" : undefined}>
          {formatRulDays(row.rul_days)}
        </span>
      ),
    },
    {
      id: "lead",
      header: "Part lead time",
      width: "8rem",
      align: "right",
      cell: (row) => `${formatNumber(row.lead_time_days)} d`,
    },
    {
      id: "cost",
      header: "Exposure",
      width: "7.5rem",
      align: "right",
      cell: (row) => formatCurrency(row.estimated_cost_impact),
    },
  ];

  if (overview.isError) {
    return (
      <>
        <PageHeader title="Command Centre" />
        <Card>
          <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Command Centre"
        description={
          overview.data?.computed_date
            ? `Scored from telematics up to ${formatDate(overview.data.computed_date)}. Every figure below is for the current scope.`
            : "Fleet health, ranked by what needs attention first."
        }
      />

      {overview.isPending || !kpis ? (
        <SkeletonKpiRow />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KpiTile
            label="Vehicles monitored"
            value={kpis.vehicles_monitored}
            icon={Truck}
            format={formatNumber}
            hint={`${formatNumber(kpis.components_tracked)} component types scored on every vehicle`}
          />
          <KpiTile
            label="Red-tier components"
            value={kpis.red_count}
            icon={AlertTriangle}
            tone="red"
            format={formatNumber}
            hint={
              kpis.escalated_count > 0
                ? `${formatNumber(kpis.escalated_count)} escalated on remaining life, not probability`
                : `${formatNumber(kpis.amber_count)} more in amber`
            }
          />
          <KpiTile
            label="Inside 30-day life"
            value={kpis.inside_30_day_rul}
            icon={Timer}
            tone="amber"
            format={formatNumber}
            hint="Long enough to order the part and book the slot"
          />
          <KpiTile
            label="Cost exposure"
            value={kpis.total_cost_exposure}
            icon={Wallet}
            format={(value) => formatCurrency(value)}
            hint={
              <>
                <span className="text-risk-green">
                  {formatCurrency(kpis.avoidable_cost)} avoidable
                </span>{" "}
                by replacing on plan
              </>
            }
          />
        </div>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader
            title="Risk mix"
            description="Every tracked component, by tier."
          />
          <CardBody>
            {overview.isPending || !overview.data ? (
              <SkeletonCard height="h-52" className="border-0 p-0" />
            ) : (
              <TierDonut tiers={overview.data.tiers} />
            )}
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader
            title="Failures and preventive swaps"
            description="Twelve months of job cards. Preventive replacements rising against falling failures is the product working."
          />
          <CardBody>
            {overview.isPending || !overview.data ? (
              <SkeletonCard height="h-56" className="border-0 p-0" />
            ) : overview.data.failure_trend.length === 0 ? (
              <EmptyState
                compact
                icon={TrendingDown}
                title="No service history yet"
                description="Failure trends appear once job cards exist for this scope."
              />
            ) : (
              <>
                <FailureTrendChart points={overview.data.failure_trend} />
                {isPartialMonth(overview.data.failure_trend.at(-1)?.month) ? (
                  <p className="mt-2 text-[0.75rem] text-faint">
                    The final point is the current month, which is still in progress.
                  </p>
                ) : null}
              </>
            )}
          </CardBody>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Top precursor signals"
            description="Mean weight across every deployed rule - what the fleet fails on."
          />
          <CardBody>
            {overview.isPending || !overview.data ? (
              <SkeletonCard height="h-56" className="border-0 p-0" />
            ) : overview.data.top_signals.length === 0 ? (
              <EmptyState
                compact
                title="No rules deployed yet"
                description="Signal weights appear once a rule is deployed in Rule Studio."
                action={
                  <Link to="/rules" className="text-[0.8125rem] text-accent hover:text-accent-ink">
                    Open Rule Studio
                  </Link>
                }
              />
            ) : (
              <SignalWeightBars signals={overview.data.top_signals} />
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title={isSingleCustomer ? "Cost exposure by component" : "Cost exposure by customer"}
            description={
              isSingleCustomer
                ? "Where this fleet's exposure sits, and how much of it planning removes."
                : "Total exposure per operator, with the share that planning removes."
            }
          />
          <CardBody>
            {isSingleCustomer ? (
              componentExposure.isPending || !componentExposure.data ? (
                <SkeletonCard height="h-56" className="border-0 p-0" />
              ) : (
                <ExposureBars
                  rows={componentExposure.data.rows.slice(0, 8).map((row) => ({
                    label: row.label,
                    exposure: row.exposure,
                    avoidable: row.avoidable,
                    meta: [
                      { label: "Red components", value: formatNumber(row.red_count) },
                      { label: "Components tracked", value: formatNumber(row.components) },
                    ],
                  }))}
                />
              )
            ) : overview.isPending || !overview.data ? (
              <SkeletonCard height="h-56" className="border-0 p-0" />
            ) : (
              <ExposureBars
                rows={overview.data.cost_by_customer.map((row) => ({
                  label: row.customer_name,
                  exposure: row.cost_exposure,
                  // The overview's per-customer rows carry no avoidable split,
                  // so nothing is drawn for it rather than a guessed share.
                  avoidable: 0,
                  meta: [
                    { label: "Vehicles", value: formatNumber(row.vehicles) },
                    { label: "Red components", value: formatNumber(row.red_count) },
                    {
                      label: "Per vehicle",
                      value: formatCurrency(row.exposure_per_vehicle, { compact: false }),
                    },
                  ],
                }))}
              />
            )}
          </CardBody>
        </Card>
      </div>

      <div className="mt-4">
        <Card>
          <CardHeader
            title="Needs attention today"
            description="Escalations first, then the highest exposure. Open a row to see the evidence behind it."
            action={
              <Link
                to="/fleet?tier=RED"
                className="inline-flex items-center gap-1 text-[0.8125rem] text-accent transition-colors hover:text-accent-ink"
              >
                All red components
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            }
          />
          <CardBody className="px-0 pb-0">
            {overview.isPending || !overview.data ? (
              <SkeletonTable rows={6} columns={7} className="rounded-none border-x-0 border-b-0" />
            ) : (
              <DataTable
                label="Components needing attention today"
                columns={attentionColumns}
                rows={overview.data.needs_attention}
                getRowId={(row) => `${row.vin}-${row.part_code}`}
                onRowClick={(row) => navigate(`/fleet/${row.vin}?part=${row.part_code}`)}
                className="rounded-none border-x-0 border-b-0"
                empty={
                  <EmptyState
                    compact
                    title="Nothing needs attention in this view"
                    description="No component is red or inside its part's lead time. The fleet list has everything that is being monitored."
                    action={
                      <Link to="/fleet" className="text-[0.8125rem] text-accent hover:text-accent-ink">
                        Open the fleet
                      </Link>
                    }
                  />
                }
              />
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}
