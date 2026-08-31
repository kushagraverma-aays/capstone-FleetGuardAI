/**
 * Risk tier, as a dot and a word.
 *
 * The word is not decoration. Spec 9 requires that colour is never the only
 * carrier of meaning, and "Red" next to a red dot is what makes this readable
 * to someone who cannot separate the two hues - and, incidentally, what makes
 * a printed screenshot still make sense.
 */

import { AlertTriangle } from "lucide-react";

import { cn } from "@/lib/cn";
import { tierStyle } from "@/lib/risk";

interface RiskBadgeProps {
  tier: string | null | undefined;
  /** Show the escalation marker. Escalated rows were lifted to RED because
   *  useful life ran out, not because probability crossed the threshold. */
  escalated?: boolean;
  /** `sm` is the table density; `md` is used in headers and drawers. */
  size?: "sm" | "md";
  className?: string;
  title?: string;
}

export function RiskBadge({
  tier,
  escalated = false,
  size = "sm",
  className,
  title,
}: RiskBadgeProps) {
  const style = tierStyle(tier);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border font-medium",
        style.soft,
        style.text,
        style.border,
        size === "sm" ? "px-2 py-0.5 text-[0.75rem]" : "px-2.5 py-1 text-[0.8125rem]",
        className,
      )}
      title={title ?? style.description}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} aria-hidden="true" />
      {style.label}
      {escalated ? (
        <AlertTriangle className="h-3 w-3" aria-label="Escalated on remaining life" />
      ) : null}
    </span>
  );
}
