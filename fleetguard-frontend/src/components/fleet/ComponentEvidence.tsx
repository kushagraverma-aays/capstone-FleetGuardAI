/**
 * The two evidence panels behind any component's score: how its probability
 * has moved, and which signals are pushing it.
 *
 * Shared by the Fleet drawer and the vehicle detail screen so the two cannot
 * drift apart - a customer who opens the drawer and then the full page must
 * see the same chart, not two interpretations of the same numbers.
 */

import { Area, AreaChart, ReferenceLine, Tooltip, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartTooltipCard,
  axisDefaults,
  useChartAnimation,
  CHART_COLORS,
} from "@/components/ui/Chart";
import { formatDate, formatPercent } from "@/lib/format";
import { tierStyle } from "@/lib/risk";
import type { DriverOut, TrendPoint } from "@/api/types";

/** Ten weeks of failure probability against the red threshold. */
export function ProbabilityTrend({
  points,
  height = 180,
}: {
  points: TrendPoint[];
  height?: number;
}) {
  const animate = useChartAnimation();

  if (points.length === 0) {
    return (
      <p className="text-[0.8125rem] text-muted">
        No scored history yet for this component - it appears here after the next scoring run.
      </p>
    );
  }

  return (
    <ChartContainer height={height}>
      <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: -22 }}>
        <defs>
          <linearGradient id="probability-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgb(var(--accent))" stopOpacity={0.28} />
            <stop offset="100%" stopColor="rgb(var(--accent))" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="week"
          tickFormatter={(value: string) => formatDate(value).slice(0, 6)}
          {...axisDefaults}
        />
        <YAxis
          domain={[0, 1]}
          tickFormatter={(value: number) => formatPercent(value)}
          {...axisDefaults}
        />
        <ReferenceLine
          y={0.7}
          stroke={tierStyle("RED").cssVar}
          strokeDasharray="4 4"
          label={{
            value: "Red at 70%",
            position: "insideTopRight",
            fill: tierStyle("RED").cssVar,
            fontSize: 10,
          }}
        />
        <Tooltip
          cursor={{ stroke: CHART_COLORS.hairline }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const point = payload[0].payload as TrendPoint;
            return (
              <ChartTooltipCard
                title={`Week of ${formatDate(point.week)}`}
                entries={[
                  { label: "Failure probability", value: formatPercent(point.probability) },
                  { label: "Health index", value: point.health_index.toFixed(1) },
                ]}
              />
            );
          }}
        />
        <Area
          type="monotone"
          dataKey="probability"
          stroke={CHART_COLORS.accent}
          strokeWidth={2}
          fill="url(#probability-fill)"
          isAnimationActive={animate}
        />
      </AreaChart>
    </ChartContainer>
  );
}

/**
 * Signal contributions, longest bar first.
 *
 * `share` arrives already scaled to 0-100 (unlike `weight`, which is a
 * fraction) - see the units note in `api/types.ts`.
 */
export function SignalDrivers({ drivers }: { drivers: DriverOut[] }) {
  if (drivers.length === 0) {
    return (
      <p className="text-[0.8125rem] text-muted">
        No rule is deployed for this component, so nothing but age is driving its score.
      </p>
    );
  }

  const widest = Math.max(...drivers.map((driver) => driver.share), 0.0001);

  return (
    <ul className="space-y-2.5">
      {drivers.map((driver) => (
        <li key={driver.signal}>
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate text-[0.8125rem] text-ink">{driver.label}</span>
            <span className="tabular shrink-0 text-[0.75rem] text-muted">
              {formatPercent(driver.share, { alreadyScaled: true })} of stress
            </span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-hairline">
            <div
              className="h-full rounded-full bg-accent"
              style={{ width: `${(driver.share / widest) * 100}%` }}
            />
          </div>
          <p className="mt-1 text-[0.6875rem] text-faint">
            Reading {driver.value.toFixed(2)} at weight{" "}
            {formatPercent(driver.weight)}
          </p>
        </li>
      ))}
    </ul>
  );
}
