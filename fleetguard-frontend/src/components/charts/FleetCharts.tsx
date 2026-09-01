/**
 * The four charts the Command Centre and Analytics share.
 *
 * They live together because they share one set of decisions: tier colours
 * only where a mark means a tier, the accent for everything else, no vertical
 * gridlines, our own tooltip, and animation that respects reduced motion.
 * Each takes already-loaded data and formats its own values - the chart knows
 * whether a number is a count, a currency or a share, and the tooltip
 * component only lays out what it is given.
 */

import {
  Bar,
  BarChart,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";

import {
  ChartContainer,
  ChartLegend,
  ChartTooltipCard,
  axisDefaults,
  gridDefaults,
  useChartAnimation,
  CHART_COLORS,
} from "@/components/ui/Chart";
import { formatCurrency, formatMonth, formatNumber, formatPercent } from "@/lib/format";
import { tierStyle } from "@/lib/risk";
import type { FailureTrendPoint, TierSlice, TopSignal } from "@/api/types";

// --- risk tier donut ---------------------------------------------------------

export function TierDonut({ tiers, height = 220 }: { tiers: TierSlice[]; height?: number }) {
  const animate = useChartAnimation();
  const total = tiers.reduce((sum, slice) => sum + slice.count, 0);

  return (
    <div>
      <div className="relative">
        <ChartContainer height={height}>
          <PieChart>
            <Pie
              data={tiers}
              dataKey="count"
              nameKey="tier"
              innerRadius="62%"
              outerRadius="88%"
              paddingAngle={2}
              stroke="none"
              isAnimationActive={animate}
            >
              {tiers.map((slice) => (
                <Cell key={slice.tier} fill={tierStyle(slice.tier).cssVar} />
              ))}
            </Pie>
            <Tooltip
              cursor={false}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const slice = payload[0].payload as TierSlice;
                return (
                  <ChartTooltipCard
                    title={`${tierStyle(slice.tier).label} tier`}
                    entries={[
                      { label: "Components", value: formatNumber(slice.count) },
                      { label: "Share", value: formatPercent(slice.share) },
                    ]}
                  />
                );
              }}
            />
          </PieChart>
        </ChartContainer>

        {/* The total sits in the hole: the donut answers "how is it split",
            and this answers "of how many" without a second card. */}
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="tabular text-[1.5rem] font-semibold leading-none text-ink">
            {formatNumber(total)}
          </span>
          <span className="mt-1 text-[0.6875rem] uppercase tracking-wider text-faint">
            Components
          </span>
        </div>
      </div>

      <ChartLegend
        className="mt-3 justify-center"
        items={tiers.map((slice) => ({
          label: `${tierStyle(slice.tier).label} ${formatNumber(slice.count)}`,
          color: tierStyle(slice.tier).cssVar,
        }))}
      />
    </div>
  );
}

// --- failure trend -----------------------------------------------------------

/**
 * Failures and preventive replacements on one axis.
 *
 * Both lines matter together: preventive swaps rising while failures fall is
 * the product working, and that story is invisible if only failures are drawn.
 * Preventive is the neutral line - it is not a risk, so it does not get a
 * risk colour.
 */
export function FailureTrendChart({
  points,
  height = 260,
}: {
  points: FailureTrendPoint[];
  height?: number;
}) {
  const animate = useChartAnimation();

  return (
    <ChartContainer height={height}>
      <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
        <CartesianGrid {...gridDefaults} />
        <XAxis dataKey="month" tickFormatter={formatMonth} {...axisDefaults} />
        <YAxis allowDecimals={false} {...axisDefaults} />
        <Tooltip
          cursor={{ stroke: CHART_COLORS.hairline }}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const point = payload[0].payload as FailureTrendPoint;
            return (
              <ChartTooltipCard
                title={formatMonth(String(label))}
                entries={[
                  {
                    label: "Failures",
                    value: formatNumber(point.failures),
                    color: tierStyle("RED").cssVar,
                  },
                  {
                    label: "Preventive swaps",
                    value: formatNumber(point.preventive),
                    color: CHART_COLORS.accent,
                  },
                ]}
              />
            );
          }}
        />
        <Legend
          verticalAlign="top"
          align="right"
          height={28}
          iconType="circle"
          iconSize={7}
          formatter={(value) => (
            <span className="text-[0.75rem] text-muted">{value}</span>
          )}
        />
        <Line
          name="Failures"
          type="monotone"
          dataKey="failures"
          stroke={tierStyle("RED").cssVar}
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 3.5 }}
          isAnimationActive={animate}
        />
        <Line
          name="Preventive"
          type="monotone"
          dataKey="preventive"
          stroke={CHART_COLORS.accent}
          strokeWidth={2}
          strokeDasharray="4 4"
          dot={false}
          activeDot={{ r: 3.5 }}
          isAnimationActive={animate}
        />
      </LineChart>
    </ChartContainer>
  );
}

// --- precursor signals -------------------------------------------------------

/**
 * Which signals the deployed rules lean on most, by mean weight.
 *
 * Horizontal bars because the labels are phrases ("Coolant temp variance"),
 * and rotated tick labels are unreadable at this size.
 */
export function SignalWeightBars({
  signals,
  height = 260,
}: {
  signals: TopSignal[];
  height?: number;
}) {
  const animate = useChartAnimation();

  return (
    <ChartContainer height={height}>
      <BarChart
        data={signals}
        layout="vertical"
        margin={{ top: 4, right: 16, bottom: 4, left: 8 }}
        barCategoryGap="28%"
      >
        <CartesianGrid {...gridDefaults} horizontal={false} vertical />
        <XAxis
          type="number"
          tickFormatter={(value: number) => formatPercent(value, { digits: 0 })}
          {...axisDefaults}
        />
        <YAxis
          type="category"
          dataKey="label"
          width={150}
          {...axisDefaults}
          tick={{ fill: CHART_COLORS.muted, fontSize: 11 }}
        />
        <Tooltip
          cursor={{ fill: CHART_COLORS.accentSoft }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const signal = payload[0].payload as TopSignal;
            return (
              <ChartTooltipCard
                title={signal.label}
                entries={[
                  { label: "Mean weight", value: formatPercent(signal.mean_weight) },
                  { label: "In rules for", value: `${formatNumber(signal.components)} components` },
                  { label: "Fleet mean value", value: signal.fleet_mean_value.toFixed(2) },
                ]}
                footnote="Weight is the share of a rule's stress term this signal carries."
              />
            );
          }}
        />
        <Bar
          dataKey="mean_weight"
          fill={CHART_COLORS.accent}
          radius={[0, 4, 4, 0]}
          isAnimationActive={animate}
        />
      </BarChart>
    </ChartContainer>
  );
}

// --- cost exposure -----------------------------------------------------------

export interface ExposureBar {
  label: string;
  exposure: number;
  avoidable: number;
  /** Shown in the tooltip: red components, vehicles, whatever the row counts. */
  meta?: { label: string; value: string }[];
}

/**
 * Two measures of the same rows, side by side.
 *
 * They are deliberately **not** stacked, because they are not parts of one
 * whole. Exposure is probability-weighted across every scored component - the
 * honest expected value. Avoidable is the gross saving on the components
 * already flagged red, priced as if each one will fail: the budget line a
 * fleet manager recognises. Drawing one inside the other would imply a share
 * relationship that does not exist.
 */
export function ExposureBars({
  rows,
  height = 260,
}: {
  rows: ExposureBar[];
  height?: number;
}) {
  const animate = useChartAnimation();
  // Some sources carry no avoidable figure (the overview's per-customer rows
  // do not). Nothing is drawn for it and the legend does not claim otherwise.
  const hasAvoidable = rows.some((row) => row.avoidable > 0);

  return (
    <div>
      <ChartContainer height={height}>
        <BarChart
          data={rows}
          layout="vertical"
          margin={{ top: 4, right: 16, bottom: 4, left: 8 }}
          barCategoryGap="26%"
          barGap={2}
        >
          <CartesianGrid {...gridDefaults} horizontal={false} vertical />
          <XAxis
            type="number"
            tickFormatter={(value: number) => formatCurrency(value)}
            {...axisDefaults}
          />
          <YAxis type="category" dataKey="label" width={140} {...axisDefaults} />
          <Tooltip
            cursor={{ fill: CHART_COLORS.accentSoft }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload as ExposureBar;
              return (
                <ChartTooltipCard
                  title={row.label}
                  entries={[
                    {
                      label: "Expected exposure",
                      value: formatCurrency(row.exposure, { compact: false }),
                      color: CHART_COLORS.accent,
                    },
                    ...(hasAvoidable
                      ? [
                          {
                            label: "Avoidable by acting now",
                            value: formatCurrency(row.avoidable, { compact: false }),
                            color: tierStyle("GREEN").cssVar,
                          },
                        ]
                      : []),
                    ...(row.meta ?? []),
                  ]}
                  footnote={
                    hasAvoidable
                      ? "Exposure is probability-weighted across every component; avoidable is the gross saving on the red ones."
                      : undefined
                  }
                />
              );
            }}
          />
          <Bar
            dataKey="exposure"
            fill={CHART_COLORS.accent}
            radius={[0, 3, 3, 0]}
            isAnimationActive={animate}
          />
          {hasAvoidable ? (
            <Bar
              dataKey="avoidable"
              fill={tierStyle("GREEN").cssVar}
              radius={[0, 3, 3, 0]}
              isAnimationActive={animate}
            />
          ) : null}
        </BarChart>
      </ChartContainer>

      <ChartLegend
        className="mt-1 pl-2"
        items={
          hasAvoidable
            ? [
                { label: "Expected exposure if these run to failure", color: CHART_COLORS.accent },
                { label: "Avoidable by replacing the red ones on plan", color: tierStyle("GREEN").cssVar },
              ]
            : [{ label: "Expected exposure if these run to failure", color: CHART_COLORS.accent }]
        }
      />
    </div>
  );
}
