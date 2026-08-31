/**
 * The heading every screen opens with: what this screen is, which scope it is
 * showing, and the actions that belong to it.
 *
 * The scope line is not decoration. Every number below it is filtered by the
 * scope switcher, and a screenshot of a screen without it is ambiguous about
 * whether it shows one customer or the whole fleet.
 */

import type { ReactNode } from "react";

import { useScopeInfo } from "@/api/queries";
import { cn } from "@/lib/cn";

interface PageHeaderProps {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  /** Set false on detail screens, which name their own subject. */
  showScope?: boolean;
  className?: string;
}

export function PageHeader({
  title,
  description,
  actions,
  showScope = true,
  className,
}: PageHeaderProps) {
  const { data: scopeInfo } = useScopeInfo();
  const scopeLabel = scopeInfo
    ? scopeInfo.is_manufacturer
      ? "All customers"
      : (scopeInfo.customer_name ?? "Customer")
    : null;

  return (
    <div className={cn("mb-6 flex flex-wrap items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        <div className="flex items-center gap-2.5">
          <h1 className="text-display font-semibold text-ink">{title}</h1>
          {showScope && scopeLabel ? (
            <span className="rounded-full border border-hairline bg-surface px-2 py-0.5 text-[0.6875rem] text-muted">
              {scopeLabel}
            </span>
          ) : null}
        </div>
        {description ? (
          <p className="mt-1.5 max-w-2xl text-sm leading-6 text-muted">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}
