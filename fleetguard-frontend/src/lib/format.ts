/**
 * Number, currency and date formatting.
 *
 * Every figure on every screen goes through one of these, so the product is
 * consistent about decimals, thousands separators and how it says "overdue".
 *
 * On currency: the analytics layer deliberately does not name a currency - the
 * seeded costs are in unspecified currency units, and inventing "USD" or "INR"
 * would be a fabricated fact. The product therefore formats amounts in the
 * grouped, abbreviated style a finance screen uses and leaves the unit
 * unstated, which is also what the assistant does when it quotes a cost.
 */

const groups = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });
const oneDecimal = new Intl.NumberFormat("en-GB", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

/** 1 234 567 -> "1,234,567" */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return groups.format(value);
}

export function formatDecimal(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/**
 * Money, abbreviated once it stops being readable in full: 8,400 stays as it
 * is, 1,240,000 becomes 1.24M. KPI tiles use the abbreviation, tables and
 * detail views pass `compact: false` to show the exact figure.
 */
export function formatCurrency(
  value: number | null | undefined,
  { compact = true }: { compact?: boolean } = {},
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  const abs = Math.abs(value);
  if (!compact || abs < 100_000) return groups.format(Math.round(value));
  if (abs < 1_000_000) return `${oneDecimal.format(value / 1_000)}K`;
  if (abs < 1_000_000_000) return `${oneDecimal.format(value / 1_000_000)}M`;
  return `${oneDecimal.format(value / 1_000_000_000)}B`;
}

/** 0.734 -> "73%". Probabilities are never shown with false precision. */
export function formatPercent(
  value: number | null | undefined,
  { digits = 0, alreadyScaled = false }: { digits?: number; alreadyScaled?: boolean } = {},
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  const scaled = alreadyScaled ? value : value * 100;
  return `${new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(scaled)}%`;
}

/**
 * Remaining useful life. Zero and negative days are "overdue" rather than
 * "0 days": a component past its projected life is a different situation from
 * one with a day left, and a column of zeros reads as a broken screen.
 */
export function formatRulDays(days: number | null | undefined): string {
  if (days === null || days === undefined || !Number.isFinite(days)) return "-";
  if (days <= 0) return "Overdue";
  if (days < 1) return "Under a day";
  if (days === 1) return "1 day";
  return `${groups.format(Math.round(days))} days`;
}

export function formatKm(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return `${groups.format(Math.round(value))} km`;
}

/** ISO date (or datetime) -> "14 Mar 2026". */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/** "2026-03" (the month buckets the analytics endpoints return) -> "Mar 2026". */
export function formatMonth(value: string): string {
  const [year, month] = value.split("-");
  const index = Number.parseInt(month ?? "", 10) - 1;
  const names = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  return index >= 0 && index < 12 ? `${names[index]} ${year}` : value;
}

/** Relative wording for alert timestamps: "4 hours ago", "yesterday". */
export function formatRelative(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return formatDate(value);
}

/** Turns a signal or status code into prose: "oil_pressure_dips" ->
 *  "Oil pressure dips". Labels come from the API wherever the API has one;
 *  this is the fallback for codes it does not label. */
export function humanise(value: string): string {
  const spaced = value.replace(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
