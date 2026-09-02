/**
 * Rule Studio - the four-step flow that builds what scores the fleet.
 *
 * Step 3 is the one that sells the product, so it is built to be watched:
 * toggling a signal re-previews the rule server-side, the weights re-normalise
 * to 1.00 in front of the viewer, and the back-test metrics move with them.
 * The preview is a *query* keyed by the selected signals, with the previous
 * result held on screen while the next arrives, so toggling feels like direct
 * manipulation rather than a form submission.
 *
 * Deployment is manufacturer-only. A customer scope sees the whole flow and a
 * disabled deploy button that says why - spec section 3 makes customers
 * read-only on rules, and demonstrating that boundary is worth more than
 * hiding it.
 */

import {
  Check,
  ChevronLeft,
  ChevronRight,
  History,
  RotateCcw,
  Rocket,
  Search,
  ShieldOff,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";

import {
  useDeployRule,
  usePartCorrelations,
  usePartHistory,
  useParts,
  useRestoreRule,
  useRule,
  useRuleHistory,
  useRulePreview,
  useScopeInfo,
} from "@/api/queries";
import type { PartOut, RuleOut, RuleSignalOut } from "@/api/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import {
  ChartContainer,
  ChartTooltipCard,
  axisDefaults,
  gridDefaults,
  useChartAnimation,
  CHART_COLORS,
} from "@/components/ui/Chart";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { SearchInput } from "@/components/ui/Input";
import { SkeletonCard, SkeletonText } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import {
  formatCurrency,
  formatDate,
  formatKm,
  formatMonth,
  formatNumber,
  formatPercent,
} from "@/lib/format";
import { CHART_COLORS as COLORS } from "@/lib/risk";

const STEPS = [
  { id: 1, label: "Component", hint: "What are we building a rule for?" },
  { id: 2, label: "History", hint: "How does it fail today?" },
  { id: 3, label: "Signals", hint: "What precedes those failures?" },
  { id: 4, label: "Deploy", hint: "Is the rule good enough to page someone?" },
] as const;

export default function RuleStudioPage() {
  const [params, setParams] = useSearchParams();
  const toast = useToast();

  const partCode = params.get("part");
  const step = Math.min(4, Math.max(1, Number.parseInt(params.get("step") ?? "1", 10) || 1));

  const { data: scopeInfo } = useScopeInfo();
  const parts = useParts();

  /** null means "nothing chosen in this visit yet" - fall back to whatever is
   *  already deployed, and only to the API's suggestion if nothing is. */
  const [signals, setSignals] = useState<string[] | null>(null);
  const [ignoreDeployed, setIgnoreDeployed] = useState(false);
  const [confirming, setConfirming] = useState(false);

  // A different component is a different rule; carrying the previous
  // component's signal selection across would be meaningless.
  useEffect(() => {
    setSignals(null);
    setIgnoreDeployed(false);
  }, [partCode]);

  // Opening a component that already has a rule must show *that* rule, not the
  // suggestion it was built from. Without this the wizard silently resets to
  // the top-correlation default, so a four-signal rule you deployed yesterday
  // reads as three signals today and looks like the deploy was lost.
  const history = useRuleHistory(partCode ?? undefined);
  const deployedSignals = useMemo(() => {
    const active = history.data?.find((rule) => rule.is_active);
    if (!active) return null;
    const included = active.signals.filter((s) => s.included).map((s) => s.signal);
    return included.length > 0 ? included : null;
  }, [history.data]);

  // Wait for the deployed rule before previewing, otherwise the first preview
  // is computed from the suggestion and is immediately thrown away.
  const historySettled = !partCode || history.isSuccess || history.isError;
  const effectiveSignals = signals ?? (ignoreDeployed ? null : deployedSignals);
  const deployedVersion = history.data?.find((rule) => rule.is_active)?.version;
  // What the viewer is looking at, so the screen can say which it is.
  const basis: "edited" | "deployed" | "suggested" =
    signals !== null ? "edited" : effectiveSignals !== null ? "deployed" : "suggested";

  const setStep = (next: number, code = partCode) => {
    const params2 = new URLSearchParams();
    if (code) params2.set("part", code);
    params2.set("step", String(next));
    setParams(params2, { replace: false });
  };

  const preview = useRulePreview(
    partCode && historySettled ? { part_code: partCode, signals: effectiveSignals } : null,
  );
  const deploy = useDeployRule();

  const selectedPart = parts.data?.find((part) => part.part_code === partCode);

  const runDeploy = () => {
    if (!partCode) return;
    deploy.mutate(
      { part_code: partCode, signals: preview.data?.selected_signals ?? signals },
      {
        onSuccess: (rule) => {
          setConfirming(false);
          toast.show({
            tone: "success",
            title: `Rule v${rule.version} deployed for ${rule.part_name}`,
            detail:
              "It scores this component from the next scoring run. Existing predictions keep the version they were scored with.",
          });
        },
        onError: (error) => {
          setConfirming(false);
          toast.show({
            tone: "error",
            title: "Deployment refused",
            detail: error.message,
          });
        },
      },
    );
  };

  return (
    <>
      <PageHeader
        title="Rule Studio"
        description="Pick a component, look at how it fails, see which signals precede those failures, and deploy the rule that scores the fleet."
        actions={
          partCode ? (
            <Button
              size="sm"
              onClick={() => setStep(1, null)}
              icon={ChevronLeft}
            >
              Change component
            </Button>
          ) : null
        }
      />

      <StepBar
        step={step}
        partCode={partCode}
        onStep={(next) => setStep(next)}
        partName={selectedPart?.part_name}
      />

      <div className="mt-4">
        {step === 1 || !partCode ? (
          <ComponentPicker
            parts={parts.data ?? []}
            loading={parts.isPending}
            error={parts.error}
            onRetry={() => void parts.refetch()}
            selected={partCode}
            onSelect={(code) => setStep(2, code)}
          />
        ) : step === 2 ? (
          <HistoryStep partCode={partCode} onNext={() => setStep(3)} />
        ) : step === 3 ? (
          <SignalStep
            partCode={partCode}
            signals={signals}
            onSignalsChange={setSignals}
            preview={preview}
            basis={basis}
            deployedVersion={deployedVersion}
            onUseSuggested={() => {
              setSignals(null);
              setIgnoreDeployed(true);
            }}
            onNext={() => setStep(4)}
          />
        ) : (
          <DeployStep
            partCode={partCode}
            preview={preview}
            canManageRules={scopeInfo?.can_manage_rules ?? false}
            onDeploy={() => setConfirming(true)}
            deploying={deploy.isPending}
          />
        )}
      </div>

      <ConfirmDialog
        open={confirming}
        title={`Deploy this rule for ${selectedPart?.part_name ?? partCode}?`}
        description="It becomes the active rule for this component. The next scoring run re-scores every vehicle with it, which moves probabilities, tiers, remaining life and cost exposure across the product. The previous version is kept and stays visible in the rule history."
        confirmLabel="Deploy rule"
        loading={deploy.isPending}
        onCancel={() => setConfirming(false)}
        onConfirm={runDeploy}
      >
        {preview.data ? (
          <div className="rounded-card border border-hairline bg-canvas px-3.5 py-3">
            <Formula formula={preview.data.formula} />
            <p className="mt-2 text-[0.75rem] text-muted">
              {formatPercent(preview.data.metrics.precision)} precision,{" "}
              {formatPercent(preview.data.metrics.coverage)} coverage, median{" "}
              {Math.round(preview.data.metrics.days_to_alert)} days of warning across{" "}
              {formatNumber(preview.data.metrics.sample_failures)} failures.
            </p>
          </div>
        ) : null}
      </ConfirmDialog>
    </>
  );
}

// --- step bar ----------------------------------------------------------------

function StepBar({
  step,
  partCode,
  partName,
  onStep,
}: {
  step: number;
  partCode: string | null;
  partName?: string;
  onStep: (step: number) => void;
}) {
  return (
    <ol className="flex flex-wrap gap-2">
      {STEPS.map((entry) => {
        const state = entry.id === step ? "current" : entry.id < step ? "done" : "todo";
        const reachable = Boolean(partCode) || entry.id === 1;
        return (
          <li key={entry.id} className="flex-1 min-w-[10rem]">
            <button
              type="button"
              disabled={!reachable}
              onClick={() => onStep(entry.id)}
              aria-current={state === "current" ? "step" : undefined}
              title={reachable ? undefined : "Choose a component first"}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-card border px-3.5 py-2.5 text-left transition-colors",
                state === "current"
                  ? "border-accent/40 bg-accent-soft"
                  : "border-hairline bg-surface",
                reachable ? "hover:bg-canvas" : "cursor-not-allowed opacity-60",
              )}
            >
              <span
                className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[0.75rem] font-medium",
                  state === "done"
                    ? "bg-accent text-white"
                    : state === "current"
                      ? "border border-accent text-accent-ink"
                      : "border border-hairline text-faint",
                )}
              >
                {state === "done" ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : entry.id}
              </span>
              <span className="min-w-0">
                <span
                  className={cn(
                    "block truncate text-[0.8125rem] font-medium",
                    state === "current" ? "text-accent-ink" : "text-ink",
                  )}
                >
                  {entry.label}
                  {entry.id === 1 && partName ? `: ${partName}` : ""}
                </span>
                <span className="block truncate text-[0.6875rem] text-muted">{entry.hint}</span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

// --- step 1: component -------------------------------------------------------

function ComponentPicker({
  parts,
  loading,
  error,
  onRetry,
  selected,
  onSelect,
}: {
  parts: PartOut[];
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  selected: string | null;
  onSelect: (partCode: string) => void;
}) {
  const [term, setTerm] = useState("");

  const grouped = useMemo(() => {
    const query = term.trim().toLowerCase();
    const matching = parts.filter(
      (part) =>
        !query ||
        part.part_name.toLowerCase().includes(query) ||
        part.category.toLowerCase().includes(query) ||
        part.part_code.toLowerCase().includes(query),
    );
    const groups = new Map<string, PartOut[]>();
    for (const part of matching) {
      const list = groups.get(part.category) ?? [];
      list.push(part);
      groups.set(part.category, list);
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [parts, term]);

  if (error) {
    return (
      <Card>
        <ErrorState error={error} onRetry={onRetry} />
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Choose a component"
        description="Every tracked component, with how it is performing today. A component with no rule is scored on age alone."
        action={
          <SearchInput
            value={term}
            onValueChange={setTerm}
            placeholder="Search components"
            className="w-56"
          />
        }
      />
      <CardBody>
        {loading ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }, (_, index) => (
              <SkeletonCard key={index} height="h-16" />
            ))}
          </div>
        ) : grouped.length === 0 ? (
          <EmptyState
            compact
            icon={Search}
            title="No component matches that"
            description="Try the category instead - the catalogue is small enough to browse."
            action={<Button onClick={() => setTerm("")}>Clear search</Button>}
          />
        ) : (
          <div className="space-y-6">
            {grouped.map(([category, items]) => (
              <section key={category}>
                <h3 className="text-label font-medium uppercase tracking-wider text-faint">
                  {category}
                </h3>
                <div className="mt-2.5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {items.map((part) => (
                    <button
                      key={part.part_code}
                      type="button"
                      onClick={() => onSelect(part.part_code)}
                      aria-pressed={selected === part.part_code}
                      className={cn(
                        "rounded-card border p-3.5 text-left transition-colors",
                        selected === part.part_code
                          ? "border-accent/40 bg-accent-soft/60"
                          : "border-hairline bg-surface hover:bg-canvas",
                      )}
                    >
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="truncate text-[0.875rem] font-medium text-ink">
                          {part.part_name}
                        </span>
                        <span className="shrink-0 text-[0.6875rem] text-faint">
                          {part.part_code}
                        </span>
                      </div>
                      <p className="mt-1 text-[0.75rem] text-muted">
                        {formatKm(part.design_life_km)} design life -{" "}
                        {formatNumber(part.failures_12m ?? 0)} failures in 12 months
                      </p>
                      <p className="mt-1.5 text-[0.75rem]">
                        {part.has_active_rule ? (
                          <span className="text-risk-green">
                            Rule deployed - {formatPercent(part.rule_precision ?? 0)} precision,{" "}
                            {formatPercent(part.rule_coverage ?? 0)} coverage
                          </span>
                        ) : (
                          <span className="text-risk-amber">
                            No rule yet - scored on age alone
                          </span>
                        )}
                      </p>
                    </button>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

// --- step 2: history ---------------------------------------------------------

function HistoryStep({ partCode, onNext }: { partCode: string; onNext: () => void }) {
  const history = usePartHistory(partCode);
  const animate = useChartAnimation();

  if (history.isError) {
    return (
      <Card>
        <ErrorState error={history.error} onRetry={() => void history.refetch()} />
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {history.isPending || !history.data
          ? Array.from({ length: 4 }, (_, index) => <SkeletonCard key={index} height="h-12" />)
          : [
              {
                label: "Failures on record",
                value: formatNumber(history.data.total_failures),
                hint: `${formatNumber(history.data.total_preventive)} preventive swaps alongside them`,
              },
              {
                label: "Median life at failure",
                value: formatPercent(history.data.median_life_used_pct, {
                  alreadyScaled: true,
                }),
                hint: `${formatKm(history.data.median_km_at_failure)} of ${formatKm(history.data.design_life_km)}`,
              },
              {
                label: "Mean downtime",
                value: `${history.data.mean_downtime_hours.toFixed(1)} h`,
                hint: "Per unplanned failure, from the job cards",
              },
              {
                label: "Warranty cost",
                value: formatCurrency(history.data.warranty_amount),
                hint: `${formatNumber(history.data.warranty_claims)} claims`,
              },
            ].map((figure) => (
              <Card key={figure.label} className="p-4">
                <p className="text-label font-medium uppercase tracking-wider text-muted">
                  {figure.label}
                </p>
                <p className="tabular mt-1.5 text-[1.5rem] font-semibold leading-none text-ink">
                  {figure.value}
                </p>
                <p className="mt-1.5 text-[0.75rem] leading-4 text-muted">{figure.hint}</p>
              </Card>
            ))}
      </div>

      <Card>
        <CardHeader
          title="Twelve months of workshop events"
          description="Failures against preventive swaps. A component whose failures dominate is one worth predicting."
          action={
            <Button variant="primary" size="sm" icon={ChevronRight} onClick={onNext}>
              Find its precursors
            </Button>
          }
        />
        <CardBody>
          {history.isPending || !history.data ? (
            <SkeletonCard height="h-56" className="border-0 p-0" />
          ) : history.data.monthly.length === 0 ? (
            <EmptyState
              compact
              title="No workshop history for this component"
              description="Without failures there is nothing to correlate against, and a rule cannot be back-tested."
            />
          ) : (
            <ChartContainer height={260}>
              <BarChart
                data={history.data.monthly}
                margin={{ top: 8, right: 8, bottom: 0, left: -18 }}
                barCategoryGap="24%"
              >
                <CartesianGrid {...gridDefaults} />
                <XAxis dataKey="month" tickFormatter={formatMonth} {...axisDefaults} />
                <YAxis allowDecimals={false} {...axisDefaults} />
                <Tooltip
                  cursor={{ fill: CHART_COLORS.accentSoft }}
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    const point = payload[0].payload as {
                      failures: number;
                      preventive: number;
                    };
                    return (
                      <ChartTooltipCard
                        title={formatMonth(String(label))}
                        entries={[
                          {
                            label: "Failures",
                            value: formatNumber(point.failures),
                            color: COLORS.accent,
                          },
                          {
                            label: "Preventive swaps",
                            value: formatNumber(point.preventive),
                            color: CHART_COLORS.faint,
                          },
                        ]}
                      />
                    );
                  }}
                />
                <Bar
                  dataKey="failures"
                  fill="rgb(var(--risk-red))"
                  radius={[3, 3, 0, 0]}
                  isAnimationActive={animate}
                />
                <Bar
                  dataKey="preventive"
                  fill={CHART_COLORS.faint}
                  radius={[3, 3, 0, 0]}
                  isAnimationActive={animate}
                />
              </BarChart>
            </ChartContainer>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

// --- step 3: signals ---------------------------------------------------------

type PreviewQuery = ReturnType<typeof useRulePreview>;

function SignalStep({
  partCode,
  signals,
  onSignalsChange,
  preview,
  basis,
  deployedVersion,
  onUseSuggested,
  onNext,
}: {
  partCode: string;
  signals: string[] | null;
  onSignalsChange: (signals: string[] | null) => void;
  preview: PreviewQuery;
  /** Where the selection on screen came from, so the card can say so. */
  basis: "edited" | "deployed" | "suggested";
  deployedVersion?: number;
  onUseSuggested: () => void;
  onNext: () => void;
}) {
  const correlations = usePartCorrelations(partCode);

  // Until the viewer touches anything, the selection is whatever the API
  // chose. The first toggle materialises that into an explicit list so the
  // menu and the preview cannot disagree about what is on.
  const selected = signals ?? preview.data?.selected_signals ?? [];

  const toggle = (signal: string) => {
    const next = selected.includes(signal)
      ? selected.filter((item) => item !== signal)
      : [...selected, signal];
    onSignalsChange(next);
  };

  if (correlations.isError) {
    return (
      <Card>
        <ErrorState error={correlations.error} onRetry={() => void correlations.refetch()} />
      </Card>
    );
  }

  const weights = preview.data?.weights ?? [];
  const total = preview.data?.weight_total ?? 0;
  const tooFew = selected.length === 0;

  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <Card className="lg:col-span-3">
        <CardHeader
          title="Which signals precede failure"
          description="Point-biserial correlation between each signal and a failure inside 90 days, computed across this component's whole history. Negative correlations are floored at zero - a signal cannot protect against failure."
        />
        <CardBody>
          {correlations.isPending || !correlations.data ? (
            <SkeletonText lines={8} />
          ) : (
            <ul className="space-y-2">
              {correlations.data.correlations.map((signal) => {
                const on = selected.includes(signal.signal);
                const weight = weights.find((entry) => entry.signal === signal.signal);
                return (
                  <li key={signal.signal}>
                    <button
                      type="button"
                      onClick={() => toggle(signal.signal)}
                      aria-pressed={on}
                      className={cn(
                        "w-full rounded-card border px-3.5 py-2.5 text-left transition-colors",
                        on ? "border-accent/40 bg-accent-soft/50" : "border-hairline hover:bg-canvas",
                      )}
                    >
                      <div className="flex items-center gap-2.5">
                        <span
                          className={cn(
                            "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                            on ? "border-accent bg-accent text-white" : "border-hairline",
                          )}
                          aria-hidden="true"
                        >
                          {on ? <Check className="h-3 w-3" /> : null}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-[0.8125rem] text-ink">
                          {signal.label}
                        </span>
                        <span className="tabular shrink-0 text-[0.75rem] text-muted">
                          r = {signal.correlation.toFixed(3)}
                        </span>
                        <span
                          className={cn(
                            "tabular w-16 shrink-0 text-right text-[0.8125rem] font-medium",
                            on ? "text-accent-ink" : "text-faint",
                          )}
                        >
                          {on && weight ? formatPercent(weight.weight) : "-"}
                        </span>
                      </div>

                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-hairline">
                        {/* Two things are drawn on one track: the raw
                            correlation (quiet) and the weight this signal
                            carries once the selection is normalised (accent).
                            Watching the second move while the first stays put
                            is the point of this step. */}
                        <div
                          className="h-full rounded-full bg-faint/60"
                          style={{ width: `${Math.min(100, signal.correlation * 250)}%` }}
                        />
                      </div>
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-hairline">
                        <div
                          className="h-full rounded-full bg-accent transition-[width] duration-500 ease-out-soft"
                          style={{ width: on && weight ? `${weight.weight * 100}%` : "0%" }}
                        />
                      </div>
                      <p className="mt-1 text-[0.6875rem] text-faint">
                        Mean {signal.mean_when_failed.toFixed(2)} before failures against{" "}
                        {signal.mean_when_healthy.toFixed(2)} otherwise - p ={" "}
                        {signal.p_value < 0.001 ? "<0.001" : signal.p_value.toFixed(3)}
                      </p>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </CardBody>
      </Card>

      <div className="space-y-4 lg:col-span-2">
        <Card>
          <CardHeader
            title="Weights"
            description="Correlations of the selected signals, normalised to sum to 1.00."
          />
          <CardBody>
            <div className="flex items-baseline justify-between">
              <span className="text-[0.8125rem] text-muted">
                {selected.length} signal{selected.length === 1 ? "" : "s"} selected
              </span>
              <span
                className={cn(
                  "tabular text-[1.25rem] font-semibold",
                  Math.abs(total - 1) < 0.005 ? "text-risk-green" : "text-risk-amber",
                )}
              >
                {total.toFixed(2)}
              </span>
            </div>

            {/* Which selection is on screen. Without this the wizard looks
                identical whether it is showing your deployed rule or the
                suggestion it was built from. */}
            <p className="mt-1.5 text-[0.75rem] text-faint">
              {basis === "deployed" ? (
                <>
                  Showing the deployed rule
                  {deployedVersion ? ` (v${deployedVersion})` : ""}.{" "}
                  <button
                    type="button"
                    onClick={onUseSuggested}
                    className="text-accent underline underline-offset-2 transition-colors hover:text-accent-ink"
                  >
                    Start from the suggested signals instead
                  </button>
                </>
              ) : basis === "suggested" ? (
                deployedVersion ? (
                  "Showing the suggested signals. Deploying replaces the rule that is live."
                ) : (
                  "Showing the suggested signals. No rule is deployed for this component yet."
                )
              ) : (
                "Your selection. Nothing changes for the fleet until you deploy it."
              )}
            </p>

            {tooFew ? (
              <p className="mt-3 text-[0.8125rem] text-risk-amber">
                With no signals selected the rule has no stress term, and the score falls back to
                age alone. Turn at least one signal back on.
              </p>
            ) : (
              <ul className="mt-3 space-y-2">
                {weights
                  .filter((weight) => weight.included)
                  .map((weight) => (
                    <WeightRow key={weight.signal} weight={weight} />
                  ))}
              </ul>
            )}

            {preview.isFetching ? (
              <p className="mt-3 text-[0.75rem] text-faint">Re-running the back-test...</p>
            ) : null}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Back-test"
            description="Replayed over the last year of this component's history, at the red threshold an operator would actually be paged by."
            action={
              <Button variant="primary" size="sm" icon={ChevronRight} onClick={onNext}>
                Review rule
              </Button>
            }
          />
          <CardBody>
            {preview.data ? (
              <MetricRow metrics={preview.data.metrics} />
            ) : (
              <SkeletonText lines={3} />
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function WeightRow({ weight }: { weight: RuleSignalOut }) {
  return (
    <li>
      <div className="flex items-baseline justify-between gap-3">
        <span className="truncate text-[0.8125rem] text-ink">{weight.label}</span>
        <span className="tabular shrink-0 text-[0.8125rem] font-medium text-accent-ink">
          {weight.weight.toFixed(3)}
        </span>
      </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-hairline">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500 ease-out-soft"
          style={{ width: `${weight.weight * 100}%` }}
        />
      </div>
    </li>
  );
}

// --- step 4: deploy ----------------------------------------------------------

function DeployStep({
  partCode,
  preview,
  canManageRules,
  onDeploy,
  deploying,
}: {
  partCode: string;
  preview: PreviewQuery;
  canManageRules: boolean;
  onDeploy: () => void;
  deploying: boolean;
}) {
  const active = useRule(partCode);
  const history = useRuleHistory(partCode);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="The rule"
          description="The weighted sum is the rule's stress term. The health index combines it with the component's age, and the failure probability every screen shows is derived from that index - which is why a rule alone never sets the number."
          action={
            canManageRules ? (
              <Button variant="primary" icon={Rocket} onClick={onDeploy} loading={deploying}>
                Deploy rule
              </Button>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-lg border border-hairline px-2.5 py-1.5 text-[0.75rem] text-muted">
                <ShieldOff className="h-3.5 w-3.5" aria-hidden="true" />
                Customer views are read-only on rules
              </span>
            )
          }
        />
        <CardBody>
          {preview.isError ? (
            <ErrorState error={preview.error} onRetry={() => void preview.refetch()} compact />
          ) : preview.isPending || !preview.data ? (
            <SkeletonText lines={4} />
          ) : (
            <>
              <div className="rounded-card border border-hairline bg-canvas px-4 py-3.5">
                <Formula formula={preview.data.formula} />
              </div>
              <div className="mt-4">
                <MetricRow metrics={preview.data.metrics} expanded />
              </div>
            </>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Deployed versions"
          description="Every rule ever active for this component. Comparing a version against the one in force is how a change gets justified."
          action={
            active.data ? (
              <span className="inline-flex items-center gap-1.5 text-[0.75rem] text-muted">
                <History className="h-3.5 w-3.5" aria-hidden="true" />
                v{active.data.version} in force
              </span>
            ) : null
          }
        />
        <CardBody>
          {history.isPending ? (
            <SkeletonText lines={4} />
          ) : (history.data?.length ?? 0) === 0 ? (
            <EmptyState
              compact
              title="No rule has been deployed for this component"
              description="Deploying the rule above makes it version 1, and every later version is compared against it here."
            />
          ) : (
            <RuleHistory
              partCode={partCode}
              versions={history.data ?? []}
              activeVersion={active.data?.version}
              canManageRules={canManageRules}
            />
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function RuleHistory({
  partCode,
  versions,
  activeVersion,
  canManageRules,
}: {
  partCode: string;
  versions: RuleOut[];
  activeVersion?: number;
  canManageRules: boolean;
}) {
  const [compare, setCompare] = useState<number | null>(null);
  const [restoring, setRestoring] = useState<RuleOut | null>(null);
  const restore = useRestoreRule();
  const toast = useToast();
  const activeRule = versions.find((rule) => rule.version === activeVersion) ?? versions[0];
  const comparing = versions.find((rule) => rule.version === compare);

  const runRestore = () => {
    if (!restoring) return;
    const from = restoring.version;
    restore.mutate(
      { partCode, version: from },
      {
        onSuccess: (rule) => {
          setRestoring(null);
          // The new version number is the point: it is what tells the viewer
          // this rolled forward rather than reactivating the old row.
          toast.show({
            tone: "success",
            title: `v${from} restored as v${rule.version}`,
            detail: `Re-tested against current data: ${formatPercent(rule.precision)} precision, ${formatPercent(rule.coverage)} coverage, ${Math.round(rule.days_to_alert)} days of warning.`,
          });
        },
        onError: (error) => {
          setRestoring(null);
          toast.show({ tone: "error", title: "Restore refused", detail: error.message });
        },
      },
    );
  };

  return (
    <div className="space-y-3">
      <ul className="divide-y divide-hairline rounded-card border border-hairline">
        {versions.map((rule) => (
          <li key={rule.rule_id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3.5 py-2.5">
            <span className="text-[0.8125rem] font-medium text-ink">v{rule.version}</span>
            {rule.is_active ? (
              <span className="rounded-full bg-risk-green-soft px-2 py-0.5 text-[0.6875rem] text-risk-green">
                Active
              </span>
            ) : null}
            <span className="tabular text-[0.75rem] text-muted">
              {formatPercent(rule.precision)} precision - {formatPercent(rule.coverage)} coverage -{" "}
              {Math.round(rule.days_to_alert)} days warning
            </span>
            <span className="text-[0.75rem] text-faint">
              {rule.created_by} - {formatDate(rule.created_at)}
            </span>
            {rule.version !== activeRule?.version ? (
              <div className="ml-auto flex items-center gap-3.5">
                <button
                  type="button"
                  onClick={() => setCompare(compare === rule.version ? null : rule.version)}
                  className="text-[0.75rem] text-accent transition-colors hover:text-accent-ink"
                >
                  {compare === rule.version
                    ? "Hide comparison"
                    : `Compare with v${activeRule?.version}`}
                </button>
                {canManageRules ? (
                  <button
                    type="button"
                    onClick={() => setRestoring(rule)}
                    disabled={restore.isPending}
                    className="inline-flex items-center gap-1 text-[0.75rem] text-muted transition-colors hover:text-ink disabled:opacity-50"
                  >
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                    Restore
                  </button>
                ) : null}
              </div>
            ) : null}
          </li>
        ))}
      </ul>

      {comparing && activeRule ? <RuleComparison a={comparing} b={activeRule} /> : null}

      {/*
        Worded as "roll forward", not "roll back", because that is what actually
        happens - and because a viewer who expects v5 to disappear needs to be
        told before they click, not after they see v6 appear.
      */}
      <ConfirmDialog
        open={restoring !== null}
        title={`Restore v${restoring?.version} as the active rule?`}
        description={`This deploys v${restoring?.version}'s signals as a new version rather than reactivating the old row, so nothing in the history is overwritten. It is re-tested against current data first, so its metrics may differ from those recorded when it was first deployed.`}
        confirmLabel="Restore this version"
        loading={restore.isPending}
        onCancel={() => setRestoring(null)}
        onConfirm={runRestore}
      >
        {restoring ? (
          <div className="rounded-card border border-hairline bg-canvas px-3.5 py-3">
            <Formula formula={restoring.formula} />
            <p className="mt-2 text-[0.75rem] text-muted">
              Recorded when v{restoring.version} was deployed:{" "}
              {formatPercent(restoring.precision)} precision,{" "}
              {formatPercent(restoring.coverage)} coverage,{" "}
              {Math.round(restoring.days_to_alert)} days of warning.
            </p>
          </div>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}

/**
 * Two rule versions side by side: what the change did to the metrics, and
 * which signal weights moved.
 *
 * Always drawn oldest-to-newest whichever row was clicked, because "before ->
 * after" only means anything in chronological order. The metrics are the point
 * - a signal diff on its own says what changed but not whether it helped, and
 * the card above promises that comparing is how a change gets justified.
 */
function RuleComparison({ a, b }: { a: RuleOut; b: RuleOut }) {
  const [older, newer] = a.version <= b.version ? [a, b] : [b, a];

  // More warning time is better, same as more precision and more coverage, so
  // every row here improves upwards.
  const rows = [
    {
      label: "Precision",
      before: formatPercent(older.precision),
      after: formatPercent(newer.precision),
      delta: (newer.precision - older.precision) * 100,
      unit: "pp",
    },
    {
      label: "Coverage",
      before: formatPercent(older.coverage),
      after: formatPercent(newer.coverage),
      delta: (newer.coverage - older.coverage) * 100,
      unit: "pp",
    },
    {
      label: "Warning time",
      before: `${Math.round(older.days_to_alert)} days`,
      after: `${Math.round(newer.days_to_alert)} days`,
      delta: newer.days_to_alert - older.days_to_alert,
      unit: " days",
    },
  ];

  const signals = signalDiff(older, newer);
  const metricsMoved = rows.some((row) => Math.abs(row.delta) >= 0.05);

  return (
    <div className="rounded-card border border-hairline p-3.5">
      <h4 className="text-[0.8125rem] font-medium text-ink">
        v{older.version} to v{newer.version}
      </h4>
      <p className="mt-1 text-[0.75rem] text-faint">
        Both back-tested over the same twelve months of history for this component.
      </p>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-[0.8125rem]">
          <thead>
            <tr className="text-left text-[0.6875rem] uppercase tracking-wider text-faint">
              <th className="pb-1.5 font-medium">Metric</th>
              <th className="pb-1.5 text-right font-medium">v{older.version}</th>
              <th className="pb-1.5 text-right font-medium">v{newer.version}</th>
              <th className="pb-1.5 text-right font-medium">Change</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const flat = Math.abs(row.delta) < 0.05;
              return (
                <tr key={row.label} className="border-t border-hairline">
                  <td className="py-1.5 text-ink">{row.label}</td>
                  <td className="tabular py-1.5 text-right text-muted">{row.before}</td>
                  <td className="tabular py-1.5 text-right text-ink">{row.after}</td>
                  <td
                    className={cn(
                      "tabular py-1.5 text-right font-medium",
                      flat ? "text-faint" : row.delta > 0 ? "text-risk-green" : "text-risk-red",
                    )}
                  >
                    {flat
                      ? "no change"
                      : `${row.delta > 0 ? "+" : "−"}${Math.abs(row.delta).toFixed(1)}${row.unit}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {signals.length === 0 ? (
        <p className="mt-3 text-[0.8125rem] text-muted">
          {metricsMoved
            ? "The same signals at the same weights, so the metrics above are the only difference."
            : "Identical rules. Only the version number, who deployed it and when differ."}
        </p>
      ) : (
        <ul className="mt-3 space-y-1.5 border-t border-hairline pt-3">
          {signals.map((row) => (
            <li
              key={row.signal}
              className="flex items-baseline justify-between gap-3 text-[0.8125rem]"
            >
              <span className="truncate text-ink">{row.label}</span>
              <span className="tabular shrink-0 text-muted">
                {row.before === null ? "not used" : row.before.toFixed(3)} {"->"}{" "}
                {row.after === null ? "not used" : row.after.toFixed(3)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Weight changes between two versions, oldest first.
 *
 * A rule row carries every signal, including the ones the author turned off, so
 * an unfiltered diff is mostly "0.000 -> 0.000". A signal unused in both
 * versions is not part of the change and is dropped; a weight of zero is
 * reported as "not used" rather than as a number, because that is what it means.
 */
function signalDiff(older: RuleOut, newer: RuleOut) {
  const weight = (rule: RuleOut, signal: string): number | null => {
    const found = rule.signals.find((s) => s.signal === signal);
    if (!found || !found.included || found.weight === 0) return null;
    return found.weight;
  };

  const names = new Map<string, string>();
  for (const signal of [...older.signals, ...newer.signals]) {
    names.set(signal.signal, signal.label);
  }

  return [...names.entries()]
    .map(([signal, label]) => ({
      signal,
      label,
      before: weight(older, signal),
      after: weight(newer, signal),
    }))
    .filter((row) => row.before !== null || row.after !== null)
    .filter((row) => row.before !== row.after);
}

// --- shared bits -------------------------------------------------------------

/**
 * The formula, coloured by token: weights in the accent, signal names in ink,
 * everything else quiet. Enough highlighting to read the shape of it at a
 * glance, without pulling in a syntax highlighter for one line of arithmetic.
 */
function Formula({ formula }: { formula: string }) {
  const tokens = formula.split(/(\s+)/);
  return (
    <code className="block break-words font-mono text-[0.8125rem] leading-6">
      {tokens.map((token, index) => {
        if (/^\s+$/.test(token)) return <span key={index}>{token}</span>;
        if (/^[\d.]+$/.test(token)) {
          return (
            <span key={index} className="font-medium text-accent">
              {token}
            </span>
          );
        }
        if (/^[+*=]$/.test(token)) {
          return (
            <span key={index} className="text-faint">
              {token}
            </span>
          );
        }
        return (
          <span key={index} className="text-ink">
            {token}
          </span>
        );
      })}
    </code>
  );
}

function MetricRow({
  metrics,
  expanded = false,
}: {
  metrics: {
    precision: number;
    coverage: number;
    days_to_alert: number;
    sample_failures: number;
    alert_episodes: number;
    true_positive_episodes: number;
    caught_failures: number;
    censored_episodes?: number;
  };
  expanded?: boolean;
}) {
  const cards = [
    {
      label: "Precision",
      value: formatPercent(metrics.precision),
      hint: `${formatNumber(metrics.true_positive_episodes)} of ${formatNumber(
        metrics.alert_episodes,
      )} alert episodes were followed by a failure`,
    },
    {
      label: "Coverage",
      value: formatPercent(metrics.coverage),
      hint: `${formatNumber(metrics.caught_failures)} of ${formatNumber(
        metrics.sample_failures,
      )} failures were alerted on first`,
    },
    {
      label: "Warning time",
      value: `${Math.round(metrics.days_to_alert)} days`,
      hint: "Median gap between the first alert and the failure",
    },
  ];

  return (
    <>
      <div className="grid gap-3 sm:grid-cols-3">
        {cards.map((card) => (
          <div key={card.label} className="rounded-card border border-hairline px-3.5 py-3">
            <p className="text-label font-medium uppercase tracking-wider text-muted">
              {card.label}
            </p>
            <p className="tabular mt-1 text-[1.375rem] font-semibold leading-none text-ink">
              {card.value}
            </p>
            {expanded ? (
              <p className="mt-1.5 text-[0.75rem] leading-4 text-muted">{card.hint}</p>
            ) : null}
          </div>
        ))}
      </div>

      {expanded && metrics.censored_episodes ? (
        <p className="mt-3 text-[0.75rem] leading-5 text-muted">
          {formatNumber(metrics.censored_episodes)} alert episodes were still running when the
          record ends. Their outcome is not yet observable, so they are excluded from precision
          rather than counted as mistakes - the standard treatment of a censored observation.
        </p>
      ) : null}
    </>
  );
}
