/**
 * The hero number. Big value, quiet label, one supporting line.
 *
 * The label sits above the number rather than below it: read top to bottom,
 * "Vehicles monitored / 600" is a sentence, and the eye lands on the number
 * last, which is where it should stay.
 */

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { CountUp } from "./CountUp";
import { cn } from "@/lib/cn";

interface KpiTileProps {
  label: string;
  value: number;
  format?: (value: number) => string;
  /** One short line under the number - a comparison, a share, a consequence. */
  hint?: ReactNode;
  icon?: LucideIcon;
  /** Risk-tier tint. Only pass this when the number *is* a risk count. */
  tone?: "default" | "red" | "amber" | "green";
  className?: string;
}

const TONES = {
  default: { value: "text-ink", icon: "text-muted", iconBg: "bg-canvas" },
  red: { value: "text-risk-red", icon: "text-risk-red", iconBg: "bg-risk-red-soft" },
  amber: { value: "text-risk-amber", icon: "text-risk-amber", iconBg: "bg-risk-amber-soft" },
  green: { value: "text-risk-green", icon: "text-risk-green", iconBg: "bg-risk-green-soft" },
} as const;

export function KpiTile({
  label,
  value,
  format,
  hint,
  icon: Icon,
  tone = "default",
  className,
}: KpiTileProps) {
  const tones = TONES[tone];

  return (
    <div className={cn("rounded-card border border-hairline bg-surface p-5", className)}>
      <div className="flex items-start justify-between gap-3">
        <p className="text-label font-medium uppercase tracking-wider text-muted">{label}</p>
        {Icon ? (
          <span
            className={cn(
              "flex h-7 w-7 items-center justify-center rounded-lg",
              tones.iconBg,
            )}
          >
            <Icon className={cn("h-4 w-4", tones.icon)} aria-hidden="true" />
          </span>
        ) : null}
      </div>

      <p className={cn("tabular mt-3 text-kpi font-semibold", tones.value)}>
        <CountUp value={value} format={format} />
      </p>

      {hint ? <p className="mt-2 text-[0.8125rem] leading-5 text-muted">{hint}</p> : null}
    </div>
  );
}
