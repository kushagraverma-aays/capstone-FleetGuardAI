/**
 * Numbers count up on first render (spec 9).
 *
 * Two details matter. The value animates only when it first appears, not on
 * every refetch - a KPI that re-rolls from zero every thirty seconds is a
 * distraction, not delight. And the DOM text is written imperatively from an
 * animation frame rather than through React state, so a four-second count does
 * not schedule sixty renders a second across the KPI row.
 */

import { useEffect, useRef } from "react";
import { useReducedMotion } from "framer-motion";

import { EASE_OUT } from "@/lib/motion";

interface CountUpProps {
  value: number;
  /** How the settled number should read. Also used for every frame. */
  format?: (value: number) => string;
  durationMs?: number;
  className?: string;
}

function easeOut(t: number): number {
  // The cubic-bezier the rest of the product uses, evaluated on y for a given
  // t. Close enough for a counter, and avoids pulling in a solver.
  const [, y1, , y2] = EASE_OUT;
  const inv = 1 - t;
  return 3 * inv * inv * t * y1 + 3 * inv * t * t * y2 + t * t * t;
}

export function CountUp({
  value,
  format = (n) => String(Math.round(n)),
  durationMs = 900,
  className,
}: CountUpProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const hasAnimated = useRef(false);
  const reduced = useReducedMotion();

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    if (reduced || hasAnimated.current || !Number.isFinite(value)) {
      node.textContent = format(value);
      hasAnimated.current = true;
      return;
    }

    hasAnimated.current = true;
    let frame = 0;
    const started = performance.now();

    const step = (now: number) => {
      const progress = Math.min((now - started) / durationMs, 1);
      node.textContent = format(value * easeOut(progress));
      if (progress < 1) frame = requestAnimationFrame(step);
    };

    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value, format, durationMs, reduced]);

  // The server-rendered-equivalent first paint shows the final value, so a
  // screen reader (and a viewer whose frame never fires) sees the real number.
  return (
    <span ref={ref} className={className}>
      {format(value)}
    </span>
  );
}
