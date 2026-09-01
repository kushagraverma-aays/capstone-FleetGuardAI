/**
 * Risk tiers and urgency bands: colour, label, and the words the product uses.
 *
 * Colour is never the only carrier of meaning here (spec 9, accessibility).
 * `RiskBadge` always renders the tier word next to the dot, and every chart
 * series that is coloured by tier also labels it.
 */

import type { RiskTier, UrgencyBand } from "@/api/types";

export interface TierStyle {
  /** The word shown to a person. */
  label: string;
  /** What the tier means, for tooltips and the legend. */
  description: string;
  /** Text colour class. */
  text: string;
  /** Tinted background for badges and soft fills. */
  soft: string;
  /** Border class for outlined treatments. */
  border: string;
  /** Solid fill, for the dot and for chart marks. */
  dot: string;
  /** CSS variable to hand to Recharts, which needs a colour string. */
  cssVar: string;
}

export const TIER_STYLES: Record<RiskTier, TierStyle> = {
  RED: {
    label: "Red",
    description: "Failure probability at or above 70%, or days from the end of useful life.",
    text: "text-risk-red",
    soft: "bg-risk-red-soft",
    border: "border-risk-red/30",
    dot: "bg-risk-red",
    cssVar: "rgb(var(--risk-red))",
  },
  AMBER: {
    label: "Amber",
    description: "Failure probability between 40% and 70%. Plan the replacement.",
    text: "text-risk-amber",
    soft: "bg-risk-amber-soft",
    border: "border-risk-amber/30",
    dot: "bg-risk-amber",
    cssVar: "rgb(var(--risk-amber))",
  },
  GREEN: {
    label: "Green",
    description: "Failure probability below 40%. No action needed.",
    text: "text-risk-green",
    soft: "bg-risk-green-soft",
    border: "border-risk-green/30",
    dot: "bg-risk-green",
    cssVar: "rgb(var(--risk-green))",
  },
};

export const TIER_ORDER: RiskTier[] = ["RED", "AMBER", "GREEN"];

export function tierStyle(tier: string | null | undefined): TierStyle {
  if (tier === "RED" || tier === "AMBER" || tier === "GREEN") return TIER_STYLES[tier];
  return TIER_STYLES.GREEN;
}

export interface BandStyle {
  label: string;
  /** The sentence the RUL Explorer puts under the group heading. */
  description: string;
  text: string;
  soft: string;
  cssVar: string;
}

/**
 * Overdue is its own band rather than the bottom of a sorted list: many
 * components are past their projected life, and a flat list opening with
 * hundreds of zeros reads as a broken screen instead of an urgent one.
 */
export const BAND_STYLES: Record<UrgencyBand, BandStyle> = {
  overdue: {
    label: "Overdue",
    description: "Past the projected end of useful life. Replace now.",
    text: "text-risk-red",
    soft: "bg-risk-red-soft",
    cssVar: "rgb(var(--risk-red))",
  },
  within_30_days: {
    label: "Inside 30 days",
    description: "Actionable this month - long enough to order the part and book the slot.",
    text: "text-risk-amber",
    soft: "bg-risk-amber-soft",
    cssVar: "rgb(var(--risk-amber))",
  },
  within_90_days: {
    label: "Inside 90 days",
    description: "Worth scheduling into the next service window.",
    text: "text-accent",
    soft: "bg-accent-soft",
    cssVar: "rgb(var(--accent))",
  },
  healthy: {
    label: "Beyond 90 days",
    description: "No action needed yet; monitored weekly.",
    text: "text-risk-green",
    soft: "bg-risk-green-soft",
    cssVar: "rgb(var(--risk-green))",
  },
};

export const BAND_ORDER: UrgencyBand[] = [
  "overdue",
  "within_30_days",
  "within_90_days",
  "healthy",
];

export function bandStyle(band: string | null | undefined): BandStyle {
  if (band && band in BAND_STYLES) return BAND_STYLES[band as UrgencyBand];
  return BAND_STYLES.healthy;
}

/** Chart colours that are not risk. Kept to the accent and two neutral tones -
 *  a chart with eight colours in it is decoration, not information. */
export const CHART_COLORS = {
  accent: "rgb(var(--accent))",
  accentSoft: "rgb(var(--accent) / 0.18)",
  ink: "rgb(var(--ink))",
  muted: "rgb(var(--muted))",
  faint: "rgb(var(--faint))",
  hairline: "rgb(var(--hairline))",
  grid: "rgb(var(--hairline))",
} as const;
