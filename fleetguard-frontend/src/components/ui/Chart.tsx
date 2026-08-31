/**
 * Recharts wrappers.
 *
 * Charts in this product share one visual language: no gridlines except a
 * faint horizontal set, axis labels in the muted tone at 11px, no axis lines,
 * one accent colour, and tier colours only where the mark genuinely means a
 * risk tier. Putting the defaults here means a new chart inherits all of that
 * by construction instead of by the author remembering.
 *
 * The tooltip is ours rather than the library's because the default is a white
 * box with a black border that ignores the theme and prints raw field names.
 */

import { useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";
import { ResponsiveContainer } from "recharts";

import { cn } from "@/lib/cn";
import { CHART_COLORS } from "@/lib/risk";

/** Fixed-height responsive wrapper. Recharts needs a bounded parent, and a
 *  chart that is 30% of a viewport height reads differently on every laptop. */
export function ChartContainer({
  height = 260,
  children,
  className,
}: {
  height?: number;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("w-full", className)} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        {children as React.ReactElement}
      </ResponsiveContainer>
    </div>
  );
}

/** Spread onto `<XAxis>` / `<YAxis>`. */
export const axisDefaults = {
  stroke: CHART_COLORS.faint,
  tickLine: false,
  axisLine: false,
  tick: { fill: CHART_COLORS.muted, fontSize: 11 },
} as const;

/** Spread onto `<CartesianGrid>`. Horizontal only: vertical gridlines on a
 *  time series add ink without adding information. */
export const gridDefaults = {
  stroke: CHART_COLORS.grid,
  strokeDasharray: "3 3",
  vertical: false,
} as const;

export interface TooltipEntry {
  label: string;
  value: string;
  /** A colour swatch, when the series needs identifying. */
  color?: string;
}

/**
 * The body of a tooltip, given already-formatted rows. Charts pass a `content`
 * render function to Recharts that formats its own values - the formatting
 * lives with the chart, which knows whether a number is a currency, a count or
 * a probability, and this component only lays it out.
 */
export function ChartTooltipCard({
  title,
  entries,
  footnote,
}: {
  title: ReactNode;
  entries: TooltipEntry[];
  footnote?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-hairline bg-raised px-3 py-2 shadow-pop">
      <p className="text-[0.75rem] font-medium text-ink">{title}</p>
      <ul className="mt-1.5 space-y-1">
        {entries.map((entry) => (
          <li key={entry.label} className="flex items-center gap-2 text-[0.75rem]">
            {entry.color ? (
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: entry.color }}
                aria-hidden="true"
              />
            ) : null}
            <span className="text-muted">{entry.label}</span>
            <span className="tabular ml-auto font-medium text-ink">{entry.value}</span>
          </li>
        ))}
      </ul>
      {footnote ? <p className="mt-1.5 text-[0.6875rem] text-faint">{footnote}</p> : null}
    </div>
  );
}

/** A legend that reads as a sentence of chips rather than a boxed key. */
export function ChartLegend({
  items,
  className,
}: {
  items: { label: string; color: string }[];
  className?: string;
}) {
  return (
    <ul className={cn("flex flex-wrap items-center gap-x-4 gap-y-1.5", className)}>
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 text-[0.75rem] text-muted">
          <span
            className="h-2 w-2 rounded-full"
            style={{ backgroundColor: item.color }}
            aria-hidden="true"
          />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/**
 * Whether chart entrance animations should play. Recharts animates by default
 * and has no notion of `prefers-reduced-motion`, so every series in the
 * product takes `isAnimationActive={useChartAnimation()}`.
 */
export function useChartAnimation(): boolean {
  return !useReducedMotion();
}

export { CHART_COLORS };
