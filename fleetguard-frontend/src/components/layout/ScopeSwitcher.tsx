/**
 * The customer scope switcher.
 *
 * This is the control that stands in for a login while `AUTH_ENABLED` is
 * false: "All customers" is the manufacturer view, and picking a customer puts
 * the whole product into that tenant. It writes to the session store, which
 * the API client reads when it builds the X-Customer-Scope header and which
 * every query key includes - so one click here genuinely re-scopes every
 * screen rather than filtering what is already on it.
 *
 * A customer scope is read-only on rules. That is not a UI decision to
 * re-derive: `/api/auth/me` answers with `can_manage_rules`, and the menu says
 * so plainly instead of letting the viewer discover it at a 403.
 */

import { Building2, Check, ChevronDown, Globe2 } from "lucide-react";

import { useCustomers, useScopeInfo } from "@/api/queries";
import { Menu, MenuItem, MenuLabel, MenuSeparator } from "@/components/ui/Menu";
import { cn } from "@/lib/cn";
import { formatNumber } from "@/lib/format";
import { useSession } from "@/state/session";

export function ScopeSwitcher() {
  const { scope, setScope, identity } = useSession();
  const { data: customers, isPending } = useCustomers();
  const { data: scopeInfo } = useScopeInfo();

  const current =
    scope === "all" ? null : customers?.find((customer) => customer.customer_id === scope);

  const label = scope === "all" ? "All customers" : (current?.name ?? scopeInfo?.customer_name ?? "Customer");

  // Someone signed in against one organisation has nothing to switch between,
  // and the API refuses the attempt outright rather than quietly narrowing it
  // - so offering the control would be offering a 403. It becomes a label
  // saying which organisation they are in, which is the useful half of it.
  if (identity && identity.customerId !== null) {
    return (
      <div
        className={cn(
          "flex h-9 max-w-[15rem] items-center gap-2 rounded-lg border border-hairline",
          "bg-canvas px-3 text-sm text-ink",
        )}
      >
        <Building2 className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
        <span className="truncate">{scopeInfo?.customer_name ?? label}</span>
        <span className="shrink-0 text-[0.6875rem] text-faint">Your organisation</span>
      </div>
    );
  }

  return (
    <Menu
      label="Customer scope"
      width="w-72"
      align="left"
      trigger={
        <button
          type="button"
          className={cn(
            "flex h-9 max-w-[15rem] items-center gap-2 rounded-lg border border-hairline",
            "bg-surface px-3 text-sm text-ink transition-colors hover:bg-canvas",
          )}
        >
          {scope === "all" ? (
            <Globe2 className="h-4 w-4 shrink-0 text-muted" aria-hidden="true" />
          ) : (
            <Building2 className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
          )}
          <span className="truncate">{label}</span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-faint" aria-hidden="true" />
        </button>
      }
    >
      {(close) => (
        <>
          <MenuLabel>Viewing as</MenuLabel>
          <MenuItem
            selected={scope === "all"}
            onClick={() => {
              setScope("all");
              close();
            }}
          >
            <Globe2 className="h-4 w-4 shrink-0 text-muted" aria-hidden="true" />
            <span className="flex-1">All customers</span>
            <span className="text-[0.6875rem] text-faint">Manufacturer</span>
            {scope === "all" ? <Check className="h-3.5 w-3.5 text-accent" aria-hidden="true" /> : null}
          </MenuItem>

          <MenuSeparator />
          <MenuLabel>Customers</MenuLabel>

          {isPending ? (
            <p className="px-2.5 py-2 text-[0.8125rem] text-muted">Loading customers...</p>
          ) : (
            (customers ?? []).map((customer) => (
              <MenuItem
                key={customer.customer_id}
                selected={scope === customer.customer_id}
                onClick={() => {
                  setScope(customer.customer_id);
                  close();
                }}
              >
                <Building2 className="h-4 w-4 shrink-0 text-muted" aria-hidden="true" />
                <span className="flex-1 truncate">{customer.name}</span>
                {customer.vehicle_count === undefined ? null : (
                  <span className="tabular text-[0.6875rem] text-faint">
                    {formatNumber(customer.vehicle_count)}
                  </span>
                )}
                {scope === customer.customer_id ? (
                  <Check className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
                ) : null}
              </MenuItem>
            ))
          )}

          <MenuSeparator />
          <p className="px-2.5 pb-2 pt-1 text-[0.75rem] leading-4 text-muted">
            {scopeInfo?.can_manage_rules
              ? "This view can deploy rules and see every customer's vehicles."
              : "A customer view is read-only on rules and can only reach its own vehicles."}
          </p>
        </>
      )}
    </Menu>
  );
}
