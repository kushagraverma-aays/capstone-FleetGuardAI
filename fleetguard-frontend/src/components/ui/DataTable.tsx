/**
 * The table every list screen uses.
 *
 * It is built from CSS grid rows with ARIA table roles rather than a real
 * `<table>`. That is a deliberate trade: the Fleet screen has to virtualise
 * thousands of rows, and a virtualised `<tbody>` needs absolutely positioned
 * `<tr>`s, which browsers render inconsistently and which break `colspan`
 * anyway. Grid rows virtualise cleanly, keep the header sticky, and let one
 * column definition drive both the header and the body.
 *
 * Sorting is *controlled* and server-side. The API sorts across the whole
 * result set, and sorting only the loaded page would quietly reorder 100 rows
 * out of 4,800 and look correct while being wrong.
 */

import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { useMemo, useRef, type ReactNode } from "react";

import { SkeletonTable } from "./Skeleton";
import { cn } from "@/lib/cn";
import type { SortOrder } from "@/api/types";

export interface Column<T> {
  /** Stable id, also used by the column visibility control. */
  id: string;
  header: ReactNode;
  /** Grid track for this column, e.g. "minmax(8rem, 1fr)" or "7rem". */
  width?: string;
  align?: "left" | "right";
  /** The API sort key. Only sortable when set. */
  sortKey?: string;
  cell: (row: T) => ReactNode;
  /** Hidden until the viewer turns it on in the column menu. */
  defaultHidden?: boolean;
  /** Kept out of the column visibility menu (identity columns). */
  alwaysVisible?: boolean;
}

export interface SortState {
  key: string;
  order: SortOrder;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  getRowId: (row: T) => string;
  /** Which columns are on screen. Omit to show every column. */
  visibleColumnIds?: string[];
  sort?: SortState;
  onSortChange?: (sort: SortState) => void;
  onRowClick?: (row: T) => void;
  /** Highlights the row whose detail drawer is open. */
  activeRowId?: string | null;
  loading?: boolean;
  /** Shown when there are no rows. Always designed - never a bare "no data". */
  empty?: ReactNode;
  /** Turn on for long lists. `height` then bounds the scroll container. */
  virtualized?: boolean;
  height?: number;
  rowHeight?: number;
  className?: string;
  /** Announced to screen readers, e.g. "Fleet predictions". */
  label: string;
}

export function DataTable<T>({
  columns,
  rows,
  getRowId,
  visibleColumnIds,
  sort,
  onSortChange,
  onRowClick,
  activeRowId,
  loading = false,
  empty,
  virtualized = false,
  height = 620,
  rowHeight = 52,
  className,
  label,
}: DataTableProps<T>) {
  const visible = useMemo(
    () =>
      columns.filter((column) =>
        visibleColumnIds ? visibleColumnIds.includes(column.id) : !column.defaultHidden,
      ),
    [columns, visibleColumnIds],
  );

  const template = useMemo(
    () => visible.map((column) => column.width ?? "minmax(7rem, 1fr)").join(" "),
    [visible],
  );

  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 12,
    enabled: virtualized,
  });

  if (loading) {
    return <SkeletonTable rows={8} columns={Math.min(visible.length, 7)} className={className} />;
  }

  const toggleSort = (column: Column<T>) => {
    if (!column.sortKey || !onSortChange) return;
    const isCurrent = sort !== undefined && sort.key === column.sortKey;
    onSortChange({
      key: column.sortKey,
      // First click on a new column sorts descending: on this product's
      // columns - probability, cost, remaining life - the interesting end is
      // almost always the top one.
      order: isCurrent && sort.order === "desc" ? "asc" : "desc",
    });
  };

  const header = (
    <div
      role="row"
      className="grid items-center gap-4 border-b border-hairline bg-canvas/70 px-4 backdrop-blur"
      style={{ gridTemplateColumns: template, height: "2.5rem" }}
    >
      {visible.map((column) => {
        const sorted =
          sort && column.sortKey && sort.key === column.sortKey ? sort.order : null;
        const content = (
          <span className="flex items-center gap-1 truncate">
            <span className="truncate">{column.header}</span>
            {column.sortKey ? (
              sorted === "asc" ? (
                <ArrowUp className="h-3 w-3 shrink-0 text-accent" aria-hidden="true" />
              ) : sorted === "desc" ? (
                <ArrowDown className="h-3 w-3 shrink-0 text-accent" aria-hidden="true" />
              ) : (
                <ChevronsUpDown className="h-3 w-3 shrink-0 text-faint" aria-hidden="true" />
              )
            ) : null}
          </span>
        );

        return (
          <div
            key={column.id}
            role="columnheader"
            aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
            className={cn(
              "text-label font-medium uppercase tracking-wider text-muted",
              column.align === "right" ? "text-right" : "text-left",
            )}
          >
            {column.sortKey && onSortChange ? (
              <button
                type="button"
                onClick={() => toggleSort(column)}
                className={cn(
                  "inline-flex max-w-full items-center rounded transition-colors hover:text-ink",
                  column.align === "right" ? "flex-row-reverse" : "",
                )}
              >
                {content}
              </button>
            ) : (
              content
            )}
          </div>
        );
      })}
    </div>
  );

  const renderRow = (row: T, style?: React.CSSProperties) => {
    const id = getRowId(row);
    const interactive = Boolean(onRowClick);

    return (
      <div
        key={id}
        role="row"
        style={{ gridTemplateColumns: template, height: rowHeight, ...style }}
        tabIndex={interactive ? 0 : -1}
        onClick={interactive ? () => onRowClick?.(row) : undefined}
        onKeyDown={
          interactive
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onRowClick?.(row);
                }
              }
            : undefined
        }
        className={cn(
          "grid items-center gap-4 border-b border-hairline px-4 text-sm text-ink",
          "transition-colors duration-150",
          interactive && "cursor-pointer hover:bg-canvas focus-visible:bg-canvas",
          activeRowId === id && "bg-accent-soft/70 hover:bg-accent-soft",
        )}
      >
        {visible.map((column) => (
          <div
            key={column.id}
            role="cell"
            className={cn(
              "min-w-0 truncate",
              column.align === "right" && "text-right tabular",
            )}
          >
            {column.cell(row)}
          </div>
        ))}
      </div>
    );
  };

  if (rows.length === 0) {
    return (
      <div className={cn("overflow-hidden rounded-card border border-hairline bg-surface", className)}>
        {header}
        {empty}
      </div>
    );
  }

  return (
    <div
      role="table"
      aria-label={label}
      aria-rowcount={rows.length}
      className={cn("overflow-hidden rounded-card border border-hairline bg-surface", className)}
    >
      <div role="rowgroup" className="sticky top-0 z-10">
        {header}
      </div>

      {virtualized ? (
        <div ref={scrollRef} className="scroll-thin overflow-auto" style={{ height }}>
          <div role="rowgroup" style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {virtualizer.getVirtualItems().map((item) =>
              renderRow(rows[item.index], {
                position: "absolute",
                top: 0,
                left: 0,
                right: 0,
                transform: `translateY(${item.start}px)`,
              }),
            )}
          </div>
        </div>
      ) : (
        <div role="rowgroup">{rows.map((row) => renderRow(row))}</div>
      )}
    </div>
  );
}
