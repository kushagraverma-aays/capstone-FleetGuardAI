/**
 * The account menu.
 *
 * It shows the demo user the API reports for the current scope, and states
 * plainly which permissions that identity carries - `can_write` and
 * `can_manage_rules` straight from `/api/auth/me`, not re-derived here. While
 * `AUTH_ENABLED` is false the identity follows the scope switcher, and the
 * menu says so rather than implying a sign-in that has not happened.
 */

import { KeyRound, LogOut, Monitor, Moon, ShieldCheck, Sun } from "lucide-react";

import { useScopeInfo } from "@/api/queries";
import { Menu, MenuItem, MenuLabel, MenuSeparator } from "@/components/ui/Menu";
import { cn } from "@/lib/cn";
import { useSession } from "@/state/session";
import { useTheme, type ThemeChoice } from "@/state/theme";

const THEME_OPTIONS: { value: ThemeChoice; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

function initials(name: string): string {
  const words = name.trim().split(/\s+/).slice(0, 2);
  return words.map((word) => word[0]?.toUpperCase() ?? "").join("") || "FG";
}

export function UserMenu() {
  const { data: scopeInfo } = useScopeInfo();
  const { choice, setChoice } = useTheme();
  const { token, setToken } = useSession();

  const name = scopeInfo?.full_name ?? "FleetGuard user";
  const email = scopeInfo?.email ?? "";
  const roleLabel = scopeInfo?.is_manufacturer ? "Manufacturer" : (scopeInfo?.customer_name ?? "Customer");

  return (
    <Menu
      label="Account"
      width="w-72"
      trigger={
        <button
          type="button"
          aria-label="Account menu"
          className={cn(
            "flex h-9 w-9 items-center justify-center rounded-full border border-hairline",
            "bg-canvas text-[0.75rem] font-medium text-ink transition-colors hover:bg-surface",
          )}
        >
          {initials(name)}
        </button>
      }
    >
      {(close) => (
        <>
          <div className="px-2.5 py-2">
            <p className="truncate text-[0.8125rem] font-medium text-ink">{name}</p>
            {email ? <p className="truncate text-[0.75rem] text-muted">{email}</p> : null}
            <p className="mt-1.5 inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2 py-0.5 text-[0.6875rem] text-accent-ink">
              <ShieldCheck className="h-3 w-3" aria-hidden="true" />
              {roleLabel}
            </p>
          </div>

          <div className="px-2.5 pb-2 text-[0.75rem] leading-4 text-muted">
            {scopeInfo?.can_manage_rules
              ? "Can acknowledge alerts, raise work orders and deploy rules."
              : "Can acknowledge alerts and raise work orders. Rule deployment is manufacturer-only."}
          </div>

          <MenuSeparator />
          <MenuLabel>Appearance</MenuLabel>
          {THEME_OPTIONS.map((option) => (
            <MenuItem
              key={option.value}
              selected={choice === option.value}
              onClick={() => setChoice(option.value)}
            >
              <option.icon className="h-4 w-4 shrink-0 text-muted" aria-hidden="true" />
              {option.label}
            </MenuItem>
          ))}

          <MenuSeparator />
          {scopeInfo?.auth_enabled === false ? (
            <p className="flex items-start gap-2 px-2.5 py-2 text-[0.75rem] leading-4 text-muted">
              <KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              Sign-in is turned off in this deployment. The scope switcher selects the
              identity; turning AUTH_ENABLED on moves that to a real token with no UI change.
            </p>
          ) : (
            <MenuItem
              onClick={() => {
                setToken(null);
                close();
              }}
              disabled={!token}
            >
              <LogOut className="h-4 w-4 shrink-0 text-muted" aria-hidden="true" />
              {token ? "Sign out" : "Not signed in"}
            </MenuItem>
          )}
        </>
      )}
    </Menu>
  );
}
