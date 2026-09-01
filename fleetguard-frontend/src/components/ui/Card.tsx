/**
 * The surface everything sits on: flat, 1px hairline, 14px radius, no shadow.
 * Shadows are reserved for things that float above the page (see `Drawer`),
 * so that elevation still means something when it appears.
 */

import { motion, useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { entrance } from "@/lib/motion";

interface CardProps {
  children: ReactNode;
  className?: string;
  /** Set on cards that appear inside an already-animating list, so the
   *  entrance is not played twice. */
  animate?: boolean;
  as?: "div" | "section" | "article";
}

export function Card({ children, className, animate = true, as = "div" }: CardProps) {
  const reduced = useReducedMotion();
  const Component = motion[as];

  return (
    <Component
      variants={entrance(reduced)}
      initial={animate ? "hidden" : false}
      animate={animate ? "visible" : undefined}
      className={cn(
        "rounded-card border border-hairline bg-surface",
        className,
      )}
    >
      {children}
    </Component>
  );
}

interface CardHeaderProps {
  title: ReactNode;
  /** One quiet sentence. Say what the card is for, not what it obviously is. */
  description?: ReactNode;
  /** Filters, a link, a menu. */
  action?: ReactNode;
  className?: string;
}

export function CardHeader({ title, description, action, className }: CardHeaderProps) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-4 px-5 pt-5",
        description ? "pb-3" : "pb-4",
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="truncate text-[0.9375rem] font-medium text-ink">{title}</h2>
        {description ? (
          <p className="mt-1 text-[0.8125rem] leading-5 text-muted">{description}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function CardBody({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn("px-5 pb-5", className)}>{children}</div>;
}

export function CardFooter({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("border-t border-hairline px-5 py-3 text-[0.8125rem] text-muted", className)}>
      {children}
    </div>
  );
}
