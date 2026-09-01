/**
 * Loading states.
 *
 * Spec 9 is specific: skeleton screens that match the final layout, never a
 * spinner on a full page. The point is that the page does not jump when the
 * data lands - so these components take the same shape arguments as the real
 * ones (`rows`, `columns`, `tiles`) and occupy the same space.
 *
 * The shimmer is a translating highlight rather than a pulsing opacity: a
 * whole screen breathing in and out is more distracting than a screen that
 * quietly sweeps. Reduced-motion viewers get the still block (see index.css).
 */

import { cn } from "@/lib/cn";

export function Skeleton({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative block overflow-hidden rounded-md bg-hairline/70",
        "after:absolute after:inset-0 after:-translate-x-full after:animate-shimmer",
        "after:bg-gradient-to-r after:from-transparent after:via-surface/60 after:to-transparent",
        className,
      )}
    />
  );
}

/** Text lines of decreasing width, which is what a paragraph looks like. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          className={cn("h-3", index === lines - 1 ? "w-2/3" : "w-full")}
        />
      ))}
    </div>
  );
}

export function SkeletonKpiRow({ tiles = 4 }: { tiles?: number }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: tiles }, (_, index) => (
        <div key={index} className="rounded-card border border-hairline bg-surface p-5">
          <Skeleton className="h-2.5 w-24" />
          <Skeleton className="mt-4 h-9 w-32" />
          <Skeleton className="mt-3 h-2.5 w-40" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonCard({
  height = "h-64",
  className,
}: {
  height?: string;
  className?: string;
}) {
  return (
    <div className={cn("rounded-card border border-hairline bg-surface p-5", className)}>
      <Skeleton className="h-3 w-32" />
      <Skeleton className={cn("mt-4 w-full", height)} />
    </div>
  );
}

/** Matches `DataTable`'s density exactly, so the rows do not shift by a pixel
 *  when the real data arrives. */
export function SkeletonTable({
  rows = 8,
  columns = 6,
  className,
}: {
  rows?: number;
  columns?: number;
  className?: string;
}) {
  return (
    <div className={cn("overflow-hidden rounded-card border border-hairline bg-surface", className)}>
      <div className="flex h-10 items-center gap-4 border-b border-hairline bg-canvas/60 px-4">
        {Array.from({ length: columns }, (_, index) => (
          <Skeleton key={index} className="h-2.5 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }, (_, rowIndex) => (
        <div
          key={rowIndex}
          className="flex h-[3.25rem] items-center gap-4 border-b border-hairline px-4 last:border-b-0"
        >
          {Array.from({ length: columns }, (_, columnIndex) => (
            <Skeleton
              key={columnIndex}
              className={cn("h-3 flex-1", columnIndex === 0 ? "max-w-[9rem]" : "max-w-[7rem]")}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
