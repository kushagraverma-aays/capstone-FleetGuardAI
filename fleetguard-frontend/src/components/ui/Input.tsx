/**
 * Text and search inputs.
 *
 * The search field carries the clear button and the keyboard shortcut hint, so
 * every search box in the product behaves the same way: type to filter, press
 * Escape to clear, and see a visible affordance for both.
 */

import { Search, X } from "lucide-react";
import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/cn";

const FIELD =
  "h-9 w-full rounded-lg border border-hairline bg-surface px-3 text-sm text-ink " +
  "placeholder:text-faint transition-colors focus:border-accent/60";

export const TextInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function TextInput({ className, ...rest }, ref) {
    return <input ref={ref} className={cn(FIELD, className)} {...rest} />;
  },
);

interface SearchInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> {
  value: string;
  onValueChange: (value: string) => void;
  /** e.g. "Ctrl K" - rendered on the right when the field is empty. */
  shortcutHint?: ReactNode;
  className?: string;
}

export const SearchInput = forwardRef<HTMLInputElement, SearchInputProps>(function SearchInput(
  { value, onValueChange, shortcutHint, className, placeholder = "Search", ...rest },
  ref,
) {
  return (
    <div className={cn("relative", className)}>
      <Search
        className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint"
        aria-hidden="true"
      />
      <input
        ref={ref}
        type="search"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onValueChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape" && value) {
            event.preventDefault();
            onValueChange("");
          }
        }}
        className={cn(
          FIELD,
          "pl-9 pr-9",
          // The browser's own clear affordance is inconsistent across engines
          // and sits at a different offset from ours.
          "[&::-webkit-search-cancel-button]:appearance-none",
        )}
        {...rest}
      />
      {value ? (
        <button
          type="button"
          aria-label="Clear search"
          onClick={() => onValueChange("")}
          className="absolute right-2 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-faint transition-colors hover:bg-canvas hover:text-ink"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      ) : shortcutHint ? (
        <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-hairline px-1.5 py-0.5 text-[0.6875rem] text-faint">
          {shortcutHint}
        </span>
      ) : null}
    </div>
  );
});
