/**
 * The small radial gauge on each component card.
 *
 * It shows the **health index**, which is the product's single source of truth
 * (spec 6.5): failure probability is derived from it and RUL projects it
 * forward, which is why one dial can stand for all three. The arc is coloured
 * by risk tier and the number is written in the middle, so the reading does
 * not depend on judging an angle - or on telling amber from red.
 */

import { useReducedMotion } from "framer-motion";

import { cn } from "@/lib/cn";
import { tierStyle } from "@/lib/risk";

interface HealthGaugeProps {
  /** 0-100. */
  value: number;
  tier: string;
  size?: number;
  /** Small caption under the number. */
  caption?: string;
  className?: string;
}

export function HealthGauge({ value, tier, size = 76, caption, className }: HealthGaugeProps) {
  const reduced = useReducedMotion();
  const style = tierStyle(tier);
  const clamped = Math.max(0, Math.min(100, value));

  const stroke = 6;
  const radius = (size - stroke) / 2;
  // A 270-degree arc with the gap at the bottom: a full ring reads as a pie
  // chart, and the gap gives the eye a start and an end.
  const circumference = 2 * Math.PI * radius;
  const arc = circumference * 0.75;
  const filled = arc * (clamped / 100);

  return (
    <div className={cn("relative", className)} style={{ width: size, height: size }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="-rotate-[225deg]"
        role="img"
        aria-label={`Health index ${Math.round(clamped)} out of 100, ${style.label} tier`}
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgb(var(--hairline))"
          strokeWidth={stroke}
          strokeDasharray={`${arc} ${circumference}`}
          strokeLinecap="round"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={style.cssVar}
          strokeWidth={stroke}
          strokeDasharray={`${filled} ${circumference}`}
          strokeLinecap="round"
          style={
            reduced
              ? undefined
              : { transition: "stroke-dasharray 600ms cubic-bezier(0.22, 1, 0.36, 1)" }
          }
        />
      </svg>

      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cn("tabular text-[1.0625rem] font-semibold leading-none", style.text)}>
          {Math.round(clamped)}
        </span>
        {caption ? (
          <span className="mt-0.5 text-[0.625rem] uppercase tracking-wide text-faint">
            {caption}
          </span>
        ) : null}
      </div>
    </div>
  );
}
