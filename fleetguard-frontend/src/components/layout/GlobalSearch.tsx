/**
 * Global search over VINs, components and customers.
 *
 * Three sources, one box. The vehicle lookup goes to the API (it searches VIN,
 * model, region, customer and component server-side, within the current
 * scope); components and customers are already in the cache from the parts and
 * customers endpoints, so they filter locally and appear instantly.
 *
 * Ctrl/Cmd-K focuses the field from anywhere, which is what anyone who uses a
 * developer tool will try first.
 */

import { Building2, CornerDownLeft, Package, Truck } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useCustomers, useParts, useVehicles } from "@/api/queries";
import { SearchInput } from "@/components/ui/Input";
import { cn } from "@/lib/cn";
import { useSession } from "@/state/session";

interface Result {
  id: string;
  kind: "vehicle" | "component" | "customer";
  title: string;
  detail: string;
  onSelect: () => void;
}

const ICONS = {
  vehicle: Truck,
  component: Package,
  customer: Building2,
} as const;

/** Waits for the typing to settle before asking the API. 200ms is below the
 *  threshold where a search box feels laggy and well above per-keystroke. */
function useDebounced(value: string, delay = 200): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

export function GlobalSearch({ className }: { className?: string }) {
  const [term, setTerm] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const debounced = useDebounced(term.trim());
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { setScope } = useSession();

  const { data: vehiclePage } = useVehicles({
    search: debounced.length >= 2 ? debounced : undefined,
    limit: 5,
  });
  const { data: parts } = useParts();
  const { data: customers } = useCustomers();

  const results = useMemo<Result[]>(() => {
    const query = debounced.toLowerCase();
    if (query.length < 2) return [];

    const vehicles: Result[] = (vehiclePage?.items ?? []).slice(0, 5).map((vehicle) => ({
      id: `vehicle-${vehicle.vin}`,
      kind: "vehicle",
      title: vehicle.vin,
      detail: `${vehicle.model} - ${vehicle.customer_name}`,
      onSelect: () => navigate(`/fleet/${vehicle.vin}`),
    }));

    const components: Result[] = (parts ?? [])
      .filter(
        (part) =>
          part.part_name.toLowerCase().includes(query) ||
          part.part_code.toLowerCase().includes(query),
      )
      .slice(0, 3)
      .map((part) => ({
        id: `part-${part.part_code}`,
        kind: "component",
        title: part.part_name,
        detail: `${part.category} - open in Rule Studio`,
        onSelect: () => navigate(`/rules?part=${encodeURIComponent(part.part_code)}`),
      }));

    const tenants: Result[] = (customers ?? [])
      .filter((customer) => customer.name.toLowerCase().includes(query))
      .slice(0, 3)
      .map((customer) => ({
        id: `customer-${customer.customer_id}`,
        kind: "customer",
        title: customer.name,
        detail: `${customer.region} - switch scope to this customer`,
        onSelect: () => {
          setScope(customer.customer_id);
          navigate("/");
        },
      }));

    return [...vehicles, ...components, ...tenants];
  }, [debounced, vehiclePage, parts, customers, navigate, setScope]);

  useEffect(() => setHighlighted(0), [debounced]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const choose = (result: Result) => {
    result.onSelect();
    setTerm("");
    inputRef.current?.blur();
  };

  const open = results.length > 0 && debounced.length >= 2;

  return (
    <div className={cn("relative", className)}>
      <SearchInput
        ref={inputRef}
        value={term}
        onValueChange={setTerm}
        placeholder="Search VIN, component or customer"
        shortcutHint="Ctrl K"
        role="combobox"
        aria-expanded={open}
        aria-controls="global-search-results"
        onKeyDown={(event) => {
          if (!open) return;
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setHighlighted((index) => (index + 1) % results.length);
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setHighlighted((index) => (index - 1 + results.length) % results.length);
          } else if (event.key === "Enter") {
            event.preventDefault();
            const result = results[highlighted];
            if (result) choose(result);
          }
        }}
      />

      {open ? (
        <ul
          id="global-search-results"
          role="listbox"
          className="absolute left-0 right-0 top-11 z-40 overflow-hidden rounded-xl border border-hairline bg-raised p-1 shadow-overlay"
        >
          {results.map((result, index) => {
            const Icon = ICONS[result.kind];
            return (
              <li key={result.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={index === highlighted}
                  onMouseEnter={() => setHighlighted(index)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => choose(result)}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left",
                    index === highlighted ? "bg-canvas" : "bg-transparent",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0 text-muted" aria-hidden="true" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[0.8125rem] text-ink">{result.title}</span>
                    <span className="block truncate text-[0.75rem] text-muted">{result.detail}</span>
                  </span>
                  {index === highlighted ? (
                    <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-faint" aria-hidden="true" />
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
