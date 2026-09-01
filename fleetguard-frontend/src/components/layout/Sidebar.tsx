/**
 * Left navigation.
 *
 * Collapsible to icons, and the choice is remembered - an operator who works
 * this screen all day gets their layout back tomorrow. Below tablet width the
 * same component renders as an overlay instead of a column (see `AppShell`),
 * which is why it takes `onNavigate`: the overlay closes when a link is
 * followed, the fixed column does nothing.
 */

import {
  BarChart3,
  Bell,
  ChevronLeft,
  Gauge,
  LayoutDashboard,
  SlidersHorizontal,
  Timer,
  Truck,
  type LucideIcon,
} from "lucide-react";
import { NavLink } from "react-router-dom";

import { cn } from "@/lib/cn";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Matched exactly, for the index route. */
  end?: boolean;
  /** What the screen is for, shown as the title attribute when collapsed. */
  hint: string;
}

export const NAV_ITEMS: NavItem[] = [
  {
    to: "/",
    label: "Command Centre",
    icon: LayoutDashboard,
    end: true,
    hint: "Fleet health at a glance",
  },
  { to: "/fleet", label: "Fleet", icon: Truck, hint: "Every monitored vehicle" },
  { to: "/rul", label: "RUL Explorer", icon: Timer, hint: "Ranked by remaining useful life" },
  { to: "/rules", label: "Rule Studio", icon: SlidersHorizontal, hint: "Build and back-test rules" },
  { to: "/alerts", label: "Alerts", icon: Bell, hint: "Vendor and fleet-owner notifications" },
  { to: "/analytics", label: "Analytics", icon: BarChart3, hint: "Cost, trends and benchmarking" },
];

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onNavigate?: () => void;
  className?: string;
}

export function Sidebar({ collapsed, onToggleCollapsed, onNavigate, className }: SidebarProps) {
  return (
    <nav
      aria-label="Primary"
      className={cn(
        "flex h-full flex-col border-r border-hairline bg-surface",
        "transition-[width] duration-200 ease-out-soft",
        collapsed ? "w-[4.25rem]" : "w-60",
        className,
      )}
    >
      <div className={cn("flex h-14 items-center gap-2.5 px-4", collapsed && "justify-center px-0")}>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent">
          <Gauge className="h-[1.1rem] w-[1.1rem] text-white" aria-hidden="true" />
        </span>
        {collapsed ? null : (
          <span className="truncate text-[0.9375rem] font-semibold tracking-tight text-ink">
            FleetGuard <span className="text-accent">AI</span>
          </span>
        )}
      </div>

      <ul className="mt-2 flex-1 space-y-0.5 px-2">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              onClick={onNavigate}
              title={collapsed ? `${item.label} - ${item.hint}` : undefined}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors duration-150",
                  collapsed && "justify-center px-0",
                  isActive
                    ? "bg-accent-soft font-medium text-accent-ink"
                    : "text-muted hover:bg-canvas hover:text-ink",
                )
              }
            >
              <item.icon className="h-[1.05rem] w-[1.05rem] shrink-0" aria-hidden="true" />
              {collapsed ? <span className="sr-only">{item.label}</span> : <span className="truncate">{item.label}</span>}
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="border-t border-hairline p-2">
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          className={cn(
            "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[0.8125rem] text-muted",
            "transition-colors hover:bg-canvas hover:text-ink",
            collapsed && "justify-center px-0",
          )}
        >
          <ChevronLeft
            className={cn(
              "h-4 w-4 shrink-0 transition-transform duration-200",
              collapsed && "rotate-180",
            )}
            aria-hidden="true"
          />
          {collapsed ? null : <span>Collapse</span>}
        </button>
      </div>
    </nav>
  );
}
