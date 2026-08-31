/**
 * A multi-select filter, and the chip row that shows what is currently applied.
 *
 * Two things make this readable rather than fiddly. The trigger states the
 * selection in words ("2 tiers"), so a filtered screen never looks unfiltered.
 * And the applied filters appear as removable chips under the toolbar, because
 * a viewer who scrolled past the menus needs to see why the table is short.
 */

import { Check, ChevronDown, X } from "lucide-react";
import type { ReactNode } from "react";

import { Menu, MenuItem } from "./Menu";
import { cn } from "@/lib/cn";

export interface FilterOption<T extends string | number> {
  value: T;
  label: string;
  /** A count or a hint, shown right-aligned. */
  meta?: ReactNode;
}

interface FilterMenuProps<T extends string | number> {
  label: string;
  options: FilterOption<T>[];
  selected: T[];
  onChange: (selected: T[]) => void;
  /** Shown when the option list is empty. */
  emptyHint?: string;
  width?: string;
}

export function FilterMenu<T extends string | number>({
  label,
  options,
  selected,
  onChange,
  emptyHint = "Nothing to filter by in this view.",
  width = "w-60",
}: FilterMenuProps<T>) {
  const toggle = (value: T) => {
    onChange(
      selected.includes(value)
        ? selected.filter((item) => item !== value)
        : [...selected, value],
    );
  };

  const summary =
    selected.length === 0
      ? label
      : selected.length === 1
        ? (options.find((option) => option.value === selected[0])?.label ?? label)
        : `${label}: ${selected.length}`;

  return (
    <Menu
      label={label}
      width={width}
      align="left"
      trigger={
        <button
          type="button"
          className={cn(
            "flex h-8 max-w-[12rem] items-center gap-1.5 rounded-lg border px-2.5",
            "text-[0.8125rem] transition-colors",
            selected.length > 0
              ? "border-accent/40 bg-accent-soft text-accent-ink"
              : "border-hairline bg-surface text-muted hover:text-ink",
          )}
        >
          <span className="truncate">{summary}</span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-70" aria-hidden="true" />
        </button>
      }
    >
      {() => (
        <>
          {options.length === 0 ? (
            <p className="px-2.5 py-2 text-[0.8125rem] text-muted">{emptyHint}</p>
          ) : (
            <div className="max-h-72 overflow-y-auto">
              {options.map((option) => (
                <MenuItem
                  key={String(option.value)}
                  selected={selected.includes(option.value)}
                  onClick={() => toggle(option.value)}
                >
                  <span
                    className={cn(
                      "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                      selected.includes(option.value)
                        ? "border-accent bg-accent text-white"
                        : "border-hairline",
                    )}
                    aria-hidden="true"
                  >
                    {selected.includes(option.value) ? <Check className="h-3 w-3" /> : null}
                  </span>
                  <span className="flex-1 truncate">{option.label}</span>
                  {option.meta ? (
                    <span className="tabular text-[0.6875rem] text-faint">{option.meta}</span>
                  ) : null}
                </MenuItem>
              ))}
            </div>
          )}

          {selected.length > 0 ? (
            <button
              type="button"
              onClick={() => onChange([])}
              className="mt-1 w-full rounded-lg border-t border-hairline px-2.5 py-2 text-left text-[0.75rem] text-muted transition-colors hover:bg-canvas hover:text-ink"
            >
              Clear {label.toLowerCase()}
            </button>
          ) : null}
        </>
      )}
    </Menu>
  );
}

interface AppliedFilter {
  id: string;
  label: string;
  onRemove: () => void;
}

export function AppliedFilters({
  filters,
  onClearAll,
  className,
}: {
  filters: AppliedFilter[];
  onClearAll: () => void;
  className?: string;
}) {
  if (filters.length === 0) return null;

  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {filters.map((filter) => (
        <span
          key={filter.id}
          className="inline-flex items-center gap-1 rounded-full border border-hairline bg-surface py-0.5 pl-2.5 pr-1 text-[0.75rem] text-muted"
        >
          {filter.label}
          <button
            type="button"
            onClick={filter.onRemove}
            aria-label={`Remove filter ${filter.label}`}
            className="flex h-4 w-4 items-center justify-center rounded-full transition-colors hover:bg-canvas hover:text-ink"
          >
            <X className="h-3 w-3" aria-hidden="true" />
          </button>
        </span>
      ))}
      <button
        type="button"
        onClick={onClearAll}
        className="ml-1 text-[0.75rem] text-accent transition-colors hover:text-accent-ink"
      >
        Clear all
      </button>
    </div>
  );
}
