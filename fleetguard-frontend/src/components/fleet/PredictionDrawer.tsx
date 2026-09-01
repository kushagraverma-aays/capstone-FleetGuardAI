/**
 * The detail panel behind a row click, on the Fleet screen and the RUL
 * Explorer.
 *
 * It answers the question a row raises - "why is this red, and what do I do?"
 * - without leaving the list. Everything in it is from
 * `GET /api/predictions/{vin}/{part}`: the same numbers the API and the
 * assistant would quote, including the cross-check sentence, which is rendered
 * verbatim rather than rebuilt here.
 */

import { ArrowUpRight, ClipboardList } from "lucide-react";
import { Link } from "react-router-dom";

import { useCreateWorkOrder, usePrediction, useScopeInfo } from "@/api/queries";
import { ProbabilityTrend, SignalDrivers } from "./ComponentEvidence";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Drawer";
import { ErrorState } from "@/components/ui/EmptyState";
import { HealthGauge } from "@/components/ui/HealthGauge";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import {
  formatCurrency,
  formatDate,
  formatKm,
  formatPercent,
  formatRulDays,
} from "@/lib/format";

interface PredictionDrawerProps {
  vin: string | null;
  partCode: string | null;
  onClose: () => void;
}

export function PredictionDrawer({ vin, partCode, onClose }: PredictionDrawerProps) {
  const open = Boolean(vin && partCode);
  const detail = usePrediction(vin ?? undefined, partCode ?? undefined);
  const { data: scopeInfo } = useScopeInfo();
  const createWorkOrder = useCreateWorkOrder();
  const toast = useToast();

  const raiseWorkOrder = () => {
    if (!vin || !partCode) return;
    createWorkOrder.mutate(
      { vin, part_code: partCode, status: "draft" },
      {
        onSuccess: () =>
          toast.show({
            tone: "success",
            title: "Work order drafted",
            detail: `${detail.data?.part_name ?? partCode} on ${vin}. It is in the work order list as a draft.`,
          }),
        onError: (error) =>
          toast.show({
            tone: "error",
            title: "Could not raise the work order",
            detail: error.message,
          }),
      },
    );
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={detail.data ? detail.data.part_name : (partCode ?? "Component")}
      subtitle={
        detail.data
          ? `${detail.data.vin} - ${detail.data.customer_name} - ${detail.data.model} ${detail.data.variant}`
          : (vin ?? undefined)
      }
      footer={
        <>
          <Button
            icon={ClipboardList}
            onClick={raiseWorkOrder}
            loading={createWorkOrder.isPending}
            disabled={!scopeInfo?.can_write}
            title={
              scopeInfo?.can_write
                ? "Raise a draft work order for this component"
                : "This view is read-only"
            }
          >
            Create work order
          </Button>
          {vin ? (
            <Link to={`/fleet/${vin}?part=${partCode ?? ""}`} onClick={onClose}>
              <Button variant="primary" icon={ArrowUpRight}>
                Open vehicle
              </Button>
            </Link>
          ) : null}
        </>
      }
    >
      {detail.isPending ? (
        <div className="space-y-5">
          <Skeleton className="h-24 w-full" />
          <SkeletonText lines={2} />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : detail.isError ? (
        <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />
      ) : detail.data ? (
        <div className="space-y-6">
          <div className="flex items-center gap-5">
            <HealthGauge
              value={detail.data.health_index}
              tier={detail.data.risk_tier}
              caption="health"
              size={84}
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <RiskBadge
                  tier={detail.data.risk_tier}
                  escalated={detail.data.escalated}
                  size="md"
                />
                <span className="tabular text-[1.375rem] font-semibold text-ink">
                  {formatPercent(detail.data.failure_probability)}
                </span>
                <span className="text-[0.8125rem] text-muted">
                  chance of failure within 90 days
                </span>
              </div>
              {detail.data.escalated && detail.data.escalation_reason ? (
                <p className="mt-1.5 text-[0.8125rem] text-risk-red">
                  {detail.data.escalation_reason}
                </p>
              ) : null}
            </div>
          </div>

          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
            <Figure label="Remaining life" value={formatRulDays(detail.data.rul_days)} />
            <Figure label="Remaining distance" value={formatKm(detail.data.rul_km)} />
            <Figure
              label="Confidence"
              value={formatPercent(detail.data.model_confidence)}
              hint={`${detail.data.window_from_days}-${detail.data.window_to_days} day window`}
            />
            <Figure
              label="Life used"
              value={formatPercent(detail.data.life_used_pct, { alreadyScaled: true })}
              hint={`${formatKm(detail.data.km_on_part)} of ${formatKm(detail.data.design_life_km)}`}
            />
            <Figure
              label="Exposure"
              value={formatCurrency(detail.data.estimated_cost_impact, { compact: false })}
              hint={`${formatCurrency(detail.data.cost.avoidable_cost, { compact: false })} avoidable`}
            />
            <Figure
              label="Part lead time"
              value={`${detail.data.lead_time_days} days`}
              hint={`Scored ${formatDate(detail.data.computed_date)}`}
            />
          </dl>

          {/* The product's own reconciliation of probability and remaining
              life. Shown verbatim: if the two ever disagreed, this sentence is
              where a customer would catch it. */}
          <div className="rounded-card border border-hairline bg-canvas px-4 py-3">
            <p className="text-label font-medium uppercase tracking-wider text-faint">
              Cross-check
            </p>
            <p className="mt-1.5 text-[0.8125rem] leading-5 text-ink">
              {detail.data.cross_check}
            </p>
          </div>

          <section>
            <h3 className="text-[0.8125rem] font-medium text-ink">Probability, last 10 weeks</h3>
            <p className="mt-0.5 text-[0.75rem] text-muted">
              Against the 70% red threshold. A flat line at a high level is a component that
              has been waiting for a workshop slot.
            </p>
            <div className="mt-2">
              <ProbabilityTrend points={detail.data.trend} height={150} />
            </div>
          </section>

          <section>
            <h3 className="text-[0.8125rem] font-medium text-ink">What is driving the score</h3>
            <p className="mt-0.5 text-[0.75rem] text-muted">
              Each signal's contribution to this component's stress term, from the deployed rule.
            </p>
            <div className="mt-3">
              <SignalDrivers drivers={detail.data.drivers} />
            </div>
          </section>

          {detail.data.rule ? (
            <section className="rounded-card border border-hairline px-4 py-3">
              <p className="text-label font-medium uppercase tracking-wider text-faint">
                Rule v{detail.data.rule.version}
              </p>
              <p className="mt-1.5 break-words font-mono text-[0.75rem] leading-5 text-muted">
                {detail.data.rule.formula}
              </p>
              <p className="mt-2 text-[0.75rem] text-muted">
                Back-tested at {formatPercent(detail.data.rule.precision)} precision and{" "}
                {formatPercent(detail.data.rule.coverage)} coverage, with a median{" "}
                {Math.round(detail.data.rule.days_to_alert)} days of warning.
              </p>
            </section>
          ) : null}
        </div>
      ) : null}
    </Drawer>
  );
}

function Figure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <dt className="text-label font-medium uppercase tracking-wider text-faint">{label}</dt>
      <dd className="tabular mt-0.5 text-[0.9375rem] text-ink">{value}</dd>
      {hint ? <dd className="text-[0.75rem] text-muted">{hint}</dd> : null}
    </div>
  );
}
