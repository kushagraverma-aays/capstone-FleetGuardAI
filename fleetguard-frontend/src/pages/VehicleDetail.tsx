/**
 * One vehicle, one component at a time.
 *
 * The health strip across the top is the vehicle; everything below it is the
 * component currently selected in that strip. That structure is deliberate:
 * an operator arrives here from a row about *one* part, but the question they
 * ask next is almost always "and how is the rest of this truck?" - which the
 * strip answers in a glance without a second page.
 *
 * The selected component lives in the URL (`?part=CLG-0311`), so a link from
 * the Fleet drawer or the Command Centre lands on the right one and a shared
 * link shows the same thing to a colleague.
 */

import {
  ArrowLeft,
  ClipboardList,
  Gauge,
  MapPin,
  MessageSquareText,
  Route,
  Wrench,
} from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import {
  useCreateWorkOrder,
  usePrediction,
  useRulDetail,
  useScopeInfo,
  useVehicle,
} from "@/api/queries";
import type { ComponentHealth, ServiceEvent } from "@/api/types";
import { DegradationCurve } from "@/components/charts/DegradationCurve";
import { DraftDialog } from "@/components/fleet/DraftDialog";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { HealthGauge } from "@/components/ui/HealthGauge";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { Skeleton, SkeletonCard } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import {
  formatCurrency,
  formatDate,
  formatKm,
  formatNumber,
  formatPercent,
  formatRulDays,
} from "@/lib/format";
import { ProbabilityTrend, SignalDrivers } from "@/components/fleet/ComponentEvidence";

export default function VehicleDetailPage() {
  const { vin } = useParams<{ vin: string }>();
  const [params, setParams] = useSearchParams();
  const [draftOpen, setDraftOpen] = useState(false);
  const toast = useToast();

  const vehicle = useVehicle(vin);
  const { data: scopeInfo } = useScopeInfo();
  const createWorkOrder = useCreateWorkOrder();

  // Default to the component closest to failing: it is why this page was
  // opened in nine cases out of ten.
  const components = vehicle.data?.components ?? [];
  const requestedPart = params.get("part");
  const selectedPart =
    components.find((component) => component.part_code === requestedPart)?.part_code ??
    components[0]?.part_code;

  const prediction = usePrediction(vin, selectedPart);
  const rul = useRulDetail(vin, selectedPart);
  const selected = components.find((component) => component.part_code === selectedPart);

  const selectPart = (partCode: string) => {
    const next = new URLSearchParams(params);
    next.set("part", partCode);
    setParams(next, { replace: true });
  };

  const raiseWorkOrder = () => {
    if (!vin || !selectedPart) return;
    createWorkOrder.mutate(
      { vin, part_code: selectedPart, status: "draft" },
      {
        onSuccess: () =>
          toast.show({
            tone: "success",
            title: "Work order drafted",
            detail: `${selected?.part_name ?? selectedPart} on ${vin}.`,
          }),
        onError: (error) =>
          toast.show({ tone: "error", title: "Could not raise the work order", detail: error.message }),
      },
    );
  };

  if (vehicle.isError) {
    return (
      <>
        <BackLink />
        <PageHeader title={vin ?? "Vehicle"} showScope={false} />
        <Card>
          <ErrorState error={vehicle.error} onRetry={() => void vehicle.refetch()} />
        </Card>
      </>
    );
  }

  return (
    <>
      <BackLink />

      <PageHeader
        title={vin ?? "Vehicle"}
        showScope={false}
        description={
          vehicle.data ? (
            <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <Fact icon={MapPin} text={`${vehicle.data.customer_name} - ${vehicle.data.region}`} />
              <Fact icon={Route} text={`${vehicle.data.model} ${vehicle.data.variant}`} />
              <Fact icon={Gauge} text={formatKm(vehicle.data.total_km_driven)} />
              <Fact
                icon={Wrench}
                text={`${vehicle.data.status} - ${formatNumber(Math.round(vehicle.data.avg_km_per_day))} km/day`}
              />
            </span>
          ) : (
            "Loading vehicle..."
          )
        }
        actions={
          <>
            <Button
              icon={MessageSquareText}
              onClick={() => setDraftOpen(true)}
              disabled={!selectedPart}
            >
              Draft outreach
            </Button>
            <Button
              icon={ClipboardList}
              variant="primary"
              onClick={raiseWorkOrder}
              loading={createWorkOrder.isPending}
              disabled={!scopeInfo?.can_write || !selectedPart}
              title={scopeInfo?.can_write ? undefined : "This view is read-only"}
            >
              Create work order
            </Button>
          </>
        }
      />

      {/* --- the vehicle: one card per tracked component ------------------- */}
      {vehicle.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-[6.5rem] w-full rounded-card" />
          ))}
        </div>
      ) : components.length === 0 ? (
        <Card>
          <EmptyState
            title="Nothing scored on this vehicle yet"
            description="It is registered and sending telemetry, but no rule has scored its components. Deploy a rule in Rule Studio and run scoring."
            action={
              <Link to="/rules" className="text-[0.8125rem] text-accent hover:text-accent-ink">
                Open Rule Studio
              </Link>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {components.map((component) => (
            <ComponentCard
              key={component.part_code}
              component={component}
              active={component.part_code === selectedPart}
              onSelect={() => selectPart(component.part_code)}
            />
          ))}
        </div>
      )}

      {/* --- the selected component ---------------------------------------- */}
      {selectedPart ? (
        <>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader
                title="Probability trend"
                description="Ten weeks of scoring for this component, against the 70% red threshold."
              />
              <CardBody>
                {prediction.isError ? (
                  <ErrorState
                    error={prediction.error}
                    onRetry={() => void prediction.refetch()}
                    compact
                  />
                ) : prediction.isPending || !prediction.data ? (
                  <SkeletonCard height="h-48" className="border-0 p-0" />
                ) : (
                  <ProbabilityTrend points={prediction.data.trend} />
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                title="What is driving the score"
                description="Each signal's share of this component's stress term, from the deployed rule."
              />
              <CardBody>
                {prediction.isError ? (
                  <ErrorState
                    error={prediction.error}
                    onRetry={() => void prediction.refetch()}
                    compact
                  />
                ) : prediction.isPending || !prediction.data ? (
                  <SkeletonCard height="h-48" className="border-0 p-0" />
                ) : (
                  <SignalDrivers drivers={prediction.data.drivers} />
                )}
              </CardBody>
            </Card>
          </div>

          <Card className="mt-4">
            <CardHeader
              title="Degradation and remaining life"
              description="Health index against distance covered on this part. The dashed half is projected from the observed trend, not measured."
              action={
                rul.data ? (
                  <span className="text-[0.8125rem] text-muted">
                    {rul.data.rul_days <= 0 ? (
                      <span className="tabular text-risk-red">Overdue for replacement</span>
                    ) : (
                      <>
                        <span className="tabular text-ink">
                          {formatRulDays(rul.data.rul_days)}
                        </span>{" "}
                        left - {formatKm(rul.data.rul_km)}
                      </>
                    )}
                  </span>
                ) : null
              }
            />
            <CardBody>
              {rul.isPending || !rul.data ? (
                <SkeletonCard height="h-64" className="border-0 p-0" />
              ) : rul.isError ? (
                <ErrorState error={rul.error} onRetry={() => void rul.refetch()} compact />
              ) : (
                <>
                  <DegradationCurve
                    curve={rul.data.curve}
                    failureThreshold={rul.data.failure_threshold_index}
                    designLifeKm={rul.data.design_life_km}
                  />
                  {/* The one sentence that ties probability and remaining life
                      together. Rendered verbatim from the API so this screen
                      cannot drift from what the assistant would say. */}
                  <div className="mt-4 rounded-card border border-hairline bg-canvas px-4 py-3">
                    <p className="text-label font-medium uppercase tracking-wider text-faint">
                      Cross-check
                    </p>
                    <p className="mt-1.5 text-[0.8125rem] leading-5 text-ink">
                      {rul.data.cross_check}
                    </p>
                  </div>
                </>
              )}
            </CardBody>
          </Card>
        </>
      ) : null}

      {/* --- history -------------------------------------------------------- */}
      <Card className="mt-4">
        <CardHeader
          title="Service history"
          description="Every job card on this vehicle, most recent first. A fitment, failure or preventive swap all reset the part's clock."
        />
        <CardBody>
          {vehicle.isPending ? (
            <SkeletonCard height="h-40" className="border-0 p-0" />
          ) : (vehicle.data?.service_history.length ?? 0) === 0 ? (
            <EmptyState
              compact
              icon={Wrench}
              title="No workshop history"
              description="This vehicle has no job cards yet, so every component is running on its first fitment."
            />
          ) : (
            <ServiceTimeline
              events={vehicle.data?.service_history ?? []}
              highlightPart={selectedPart}
            />
          )}
        </CardBody>
      </Card>

      {vin && selectedPart ? (
        <DraftDialog
          open={draftOpen}
          onClose={() => setDraftOpen(false)}
          vin={vin}
          partCode={selectedPart}
          partName={selected?.part_name ?? selectedPart}
        />
      ) : null}
    </>
  );
}

function BackLink() {
  return (
    <Link
      to="/fleet"
      className="mb-3 inline-flex items-center gap-1.5 text-[0.8125rem] text-muted transition-colors hover:text-ink"
    >
      <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
      Back to the fleet
    </Link>
  );
}

function Fact({ icon: Icon, text }: { icon: typeof Gauge; text: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[0.8125rem] text-muted">
      <Icon className="h-3.5 w-3.5 text-faint" aria-hidden="true" />
      {text}
    </span>
  );
}

function ComponentCard({
  component,
  active,
  onSelect,
}: {
  component: ComponentHealth;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={cn(
        "flex items-center gap-3.5 rounded-card border p-3.5 text-left transition-colors",
        active
          ? "border-accent/40 bg-accent-soft/50"
          : "border-hairline bg-surface hover:bg-canvas",
      )}
    >
      <HealthGauge
        value={component.health_index}
        tier={component.risk_tier}
        size={62}
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[0.875rem] font-medium text-ink">{component.part_name}</p>
        <p className="mt-0.5 text-[0.75rem] text-muted">
          {formatPercent(component.failure_probability)} risk -{" "}
          {formatRulDays(component.rul_days)}
        </p>
        <div className="mt-1.5">
          <RiskBadge tier={component.risk_tier} escalated={component.escalated} />
        </div>
      </div>
    </button>
  );
}

const EVENT_STYLES: Record<string, { label: string; className: string }> = {
  failure: { label: "Failure", className: "bg-risk-red" },
  preventive: { label: "Preventive swap", className: "bg-risk-green" },
  fitment: { label: "First fitment", className: "bg-accent" },
};

function ServiceTimeline({
  events,
  highlightPart,
}: {
  events: ServiceEvent[];
  highlightPart?: string;
}) {
  return (
    <ol className="relative space-y-3 pl-5">
      <span className="absolute bottom-2 left-[0.3125rem] top-2 w-px bg-hairline" aria-hidden="true" />
      {events.map((event) => {
        const style = EVENT_STYLES[event.event_type] ?? {
          label: event.event_type,
          className: "bg-faint",
        };
        const highlighted = event.part_code === highlightPart;
        return (
          <li key={event.job_card_id} className="relative">
            <span
              className={cn(
                "absolute -left-5 top-1.5 h-2 w-2 rounded-full ring-4 ring-surface",
                style.className,
              )}
              aria-hidden="true"
            />
            <div
              className={cn(
                "flex flex-wrap items-baseline gap-x-3 gap-y-0.5 rounded-lg px-2 py-1",
                highlighted && "bg-accent-soft/60",
              )}
            >
              <span className="text-[0.8125rem] text-ink">{event.part_name}</span>
              <span className="text-[0.75rem] text-muted">{style.label}</span>
              <span className="text-[0.75rem] text-faint">{formatDate(event.event_date)}</span>
              <span className="tabular ml-auto text-[0.75rem] text-muted">
                {formatKm(event.odometer_reading)} - {formatCurrency(event.cost, { compact: false })}{" "}
                - {event.downtime_hours.toFixed(1)} h down
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}