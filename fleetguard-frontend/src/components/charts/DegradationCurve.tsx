/**
 * The degradation curve: health index against distance on the part, split into
 * what was observed and what is projected.
 *
 * The split is the point of the chart. A single line would present a
 * projection with the same confidence as a measurement; drawing the projected
 * half dashed, and marking the failure threshold it is heading for, is what
 * makes the remaining-life number arguable rather than magic.
 *
 * The two series share one point at the join - the last observed reading is
 * also the first projected one - or the line would break at the handover.
 */

import {
  Area,
  ComposedChart,
  Line,
  ReferenceLine,
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
import { formatKm } from "@/lib/format";
import { tierStyle } from "@/lib/risk";
import type { CurvePoint } from "@/api/types";

interface DegradationCurveProps {
  curve: CurvePoint[];
  /** Health index at which the component is treated as failed (30). */
  failureThreshold: number;
  /** Marked on the x-axis, so "past design life" is visible, not inferred. */
  designLifeKm?: number;
  height?: number;
}

interface Row {
  km_on_part: number;
  observed: number | null;
  projected: number | null;
}

export function DegradationCurve({
  curve,
  failureThreshold,
  designLifeKm,
  height = 280,
}: DegradationCurveProps) {
  const animate = useChartAnimation();

  const lastObservedIndex = curve.reduce(
    (last, point, index) => (point.projected ? last : index),
    -1,
  );

  const rows: Row[] = curve.map((point, index) => ({
    km_on_part: point.km_on_part,
    observed: point.projected ? null : point.health_index,
    projected:
      point.projected || index === lastObservedIndex ? point.health_index : null,
  }));

  const hasProjection = curve.some((point) => point.projected);

  return (
    <div>
      <ChartContainer height={height}>
        <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: -18 }}>
          <defs>
            <linearGradient id="curve-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgb(var(--accent))" stopOpacity={0.22} />
              <stop offset="100%" stopColor="rgb(var(--accent))" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid {...gridDefaults} />
          <XAxis
            dataKey="km_on_part"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(value: number) => `${Math.round(value / 1000)}k`}
            {...axisDefaults}
          />
          <YAxis domain={[0, 100]} {...axisDefaults} />

          <ReferenceLine
            y={failureThreshold}
            stroke={tierStyle("RED").cssVar}
            strokeDasharray="4 4"
            label={{
              value: `Failure threshold ${failureThreshold}`,
              position: "insideBottomRight",
              fill: tierStyle("RED").cssVar,
              fontSize: 10,
            }}
          />
          {designLifeKm ? (
            <ReferenceLine
              x={designLifeKm}
              stroke={CHART_COLORS.faint}
              strokeDasharray="2 4"
              label={{
                value: "Design life",
                position: "insideTopLeft",
                fill: CHART_COLORS.muted,
                fontSize: 10,
              }}
            />
          ) : null}

          <Tooltip
            cursor={{ stroke: CHART_COLORS.hairline }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload as Row;
              const isProjection = row.observed === null;
              return (
                <ChartTooltipCard
                  title={`${formatKm(row.km_on_part)} on the part`}
                  entries={[
                    {
                      label: "Health index",
                      value: (row.observed ?? row.projected ?? 0).toFixed(1),
                      color: CHART_COLORS.accent,
                    },
                  ]}
                  footnote={isProjection ? "Projected from the observed trend." : "Measured."}
                />
              );
            }}
          />

          <Area
            type="monotone"
            dataKey="observed"
            stroke="none"
            fill="url(#curve-fill)"
            isAnimationActive={animate}
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey="observed"
            stroke={CHART_COLORS.accent}
            strokeWidth={2}
            dot={false}
            isAnimationActive={animate}
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey="projected"
            stroke={CHART_COLORS.accent}
            strokeWidth={2}
            strokeDasharray="5 4"
            dot={false}
            isAnimationActive={animate}
            connectNulls={false}
          />
        </ComposedChart>
      </ChartContainer>

      <ChartLegend
        className="mt-1 justify-center"
        items={[
          { label: "Observed", color: CHART_COLORS.accent },
          ...(hasProjection
            ? [{ label: "Projected", color: CHART_COLORS.accentSoft }]
            : []),
          { label: "Failure threshold", color: tierStyle("RED").cssVar },
        ]}
      />
    </div>
  );
}
