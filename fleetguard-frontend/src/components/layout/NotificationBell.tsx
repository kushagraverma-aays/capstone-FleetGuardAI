/**
 * The notification bell and its preview.
 *
 * The count is the number of *pending* alerts in the current scope, taken from
 * the `total` of a one-row page rather than by counting a fetched list - the
 * inbox can hold thousands and the header needs one number.
 */

import { Bell, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

import { useNotifications } from "@/api/queries";
import { IconButton } from "@/components/ui/Button";
import { Menu, MenuLabel, MenuSeparator } from "@/components/ui/Menu";
import { cn } from "@/lib/cn";
import { formatRelative } from "@/lib/format";

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-risk-red",
  high: "bg-risk-amber",
  medium: "bg-accent",
};

export function NotificationBell() {
  const { data, isPending } = useNotifications({ alert_status: ["pending"], limit: 6 });
  const pending = data?.total ?? 0;

  return (
    <Menu
      label="Notifications"
      width="w-80"
      trigger={
        <IconButton
          icon={Bell}
          label={pending > 0 ? `Notifications, ${pending} pending` : "Notifications"}
          badge={pending}
        />
      }
    >
      {(close) => (
        <>
          <MenuLabel>{pending > 0 ? `${pending} pending` : "Notifications"}</MenuLabel>

          {isPending ? (
            <p className="px-2.5 py-3 text-[0.8125rem] text-muted">Loading...</p>
          ) : (data?.items.length ?? 0) === 0 ? (
            <p className="px-2.5 py-3 text-[0.8125rem] text-muted">
              Nothing pending in this view. New alerts appear here as scoring runs.
            </p>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {data?.items.map((notification) => (
                <li key={notification.id}>
                  <Link
                    to={`/alerts?focus=${notification.id}`}
                    onClick={close}
                    className="flex gap-2.5 rounded-lg px-2.5 py-2 transition-colors hover:bg-canvas"
                  >
                    <span
                      className={cn(
                        "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                        SEVERITY_STYLES[notification.severity] ?? "bg-accent",
                      )}
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[0.8125rem] text-ink">
                        {notification.title}
                      </span>
                      <span className="block truncate text-[0.75rem] text-muted">
                        {notification.vin} - {notification.part_name}
                      </span>
                      <span className="mt-0.5 block text-[0.6875rem] text-faint">
                        {notification.audience === "vendor" ? "Vendor" : "Fleet owner"} -{" "}
                        {formatRelative(notification.created_at)}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}

          <MenuSeparator />
          <Link
            to="/alerts"
            onClick={close}
            className="flex items-center justify-between rounded-lg px-2.5 py-2 text-[0.8125rem] text-accent-ink transition-colors hover:bg-canvas"
          >
            Open the alerts inbox
            <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Link>
        </>
      )}
    </Menu>
  );
}
