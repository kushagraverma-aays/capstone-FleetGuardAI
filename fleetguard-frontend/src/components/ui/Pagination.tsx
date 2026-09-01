/**
 * Offset pagination for the list endpoints, which all answer with
 * `{items, total, limit, offset}`.
 *
 * It states the range and the total in words rather than only offering arrows:
 * "1-100 of 4,812 components" tells an operator how much is behind the filter
 * they just applied, which is usually the thing they actually wanted to know.
 */

import { ChevronLeft, ChevronRight } from "lucide-react";

import { IconButton } from "./Button";
import { cn } from "@/lib/cn";
import { formatNumber } from "@/lib/format";

interface PaginationProps {
  total: number;
  limit: number;
  offset: number;
  onOffsetChange: (offset: number) => void;
  /** What is being counted, plural: "components", "vehicles", "alerts". */
  noun: string;
  className?: string;
}

export function Pagination({
  total,
  limit,
  offset,
  onOffsetChange,
  noun,
  className,
}: PaginationProps) {
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  const canGoBack = offset > 0;
  const canGoForward = last < total;

  return (
    <div className={cn("flex items-center justify-between gap-4", className)}>
      <p className="text-[0.8125rem] text-muted">
        {total === 0 ? (
          `No ${noun}`
        ) : (
          <>
            <span className="tabular text-ink">
              {formatNumber(first)}-{formatNumber(last)}
            </span>{" "}
            of <span className="tabular text-ink">{formatNumber(total)}</span> {noun}
          </>
        )}
      </p>

      <div className="flex items-center gap-1">
        <IconButton
          icon={ChevronLeft}
          label="Previous page"
          variant="secondary"
          size="sm"
          disabled={!canGoBack}
          onClick={() => onOffsetChange(Math.max(0, offset - limit))}
        />
        <IconButton
          icon={ChevronRight}
          label="Next page"
          variant="secondary"
          size="sm"
          disabled={!canGoForward}
          onClick={() => onOffsetChange(offset + limit)}
        />
      </div>
    </div>
  );
}
