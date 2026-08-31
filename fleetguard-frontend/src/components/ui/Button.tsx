/**
 * Buttons and icon buttons.
 *
 * Four variants, no more: primary for the one action a screen exists to
 * perform, secondary for everything else, ghost for toolbar controls, and
 * danger for the two or three destructive actions in the product. An app with
 * six button styles has no button style.
 */

import { Loader2, type LucideIcon } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  // The disabled primary dims the label as well as the fill. At 40% accent
  // with full-strength white text it still read as a live button on a dark
  // canvas - a read-only viewer saw a bright blue "Work order" they could not
  // press, which looks broken rather than unavailable.
  primary:
    "bg-accent text-white hover:bg-accent/90 active:bg-accent/95 " +
    "disabled:bg-accent/25 disabled:text-white/45",
  secondary:
    "border border-hairline bg-surface text-ink hover:bg-canvas active:bg-canvas disabled:text-faint",
  ghost: "text-muted hover:bg-canvas hover:text-ink disabled:text-faint",
  danger:
    "border border-risk-red/30 bg-risk-red-soft text-risk-red hover:bg-risk-red/15 disabled:opacity-50",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 gap-1.5 px-3 text-[0.8125rem]",
  md: "h-9 gap-2 px-3.5 text-sm",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: LucideIcon;
  /** Shows a spinner and disables the button. The label stays, so the button
   *  does not change width mid-click. */
  loading?: boolean;
  children?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon: Icon, loading, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      disabled={disabled || loading}
      className={cn(
        "inline-flex select-none items-center justify-center rounded-lg font-medium",
        "transition-colors duration-150 ease-out-soft disabled:cursor-not-allowed",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      ) : Icon ? (
        <Icon className="h-4 w-4" aria-hidden="true" />
      ) : null}
      {children}
    </button>
  );
});

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: LucideIcon;
  /** Required: an icon with no accessible name is a button nobody can use with
   *  a screen reader, and this is the only place to enforce that. */
  label: string;
  variant?: Variant;
  size?: Size;
  /** A dot in the corner, for the notification bell. */
  badge?: number;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon: Icon, label, variant = "ghost", size = "md", badge, className, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        "relative inline-flex items-center justify-center rounded-lg",
        "transition-colors duration-150 ease-out-soft disabled:cursor-not-allowed",
        VARIANTS[variant],
        size === "sm" ? "h-8 w-8" : "h-9 w-9",
        className,
      )}
      {...rest}
    >
      <Icon className="h-[1.05rem] w-[1.05rem]" aria-hidden="true" />
      {badge && badge > 0 ? (
        <span
          className={cn(
            "tabular absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center",
            "rounded-full bg-risk-red px-1 text-[0.625rem] font-semibold text-white",
          )}
        >
          {badge > 99 ? "99+" : badge}
        </span>
      ) : null}
    </button>
  );
});
