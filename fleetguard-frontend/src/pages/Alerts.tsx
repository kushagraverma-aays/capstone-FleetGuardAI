/**
 * Alerts - the inbox, split by who each alert was written for.
 *
 * Vendor alerts and fleet-owner alerts are different jobs done by different
 * people: one commits stock against a lead time, the other books a workshop
 * slot. Mixing them into one list means everybody reads everybody else's work.
 *
 * Acknowledging and dismissing are optimistic - the row changes on click and
 * rolls back with an explanation if the write fails - because an operator
 * working an inbox of hundreds cannot wait 200ms per click.
 */

import { BellOff, Check, ClipboardList, Undo2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  useCreateWorkOrder,
  useCustomers,
  useNotifications,
  useScopeInfo,
  useUpdateNotification,
} from "@/api/queries";
import type {
  NotificationAudience,
  NotificationOut,
  NotificationSeverity,
  NotificationStatus,
} from "@/api/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { FilterMenu } from "@/components/ui/FilterMenu";
import { SearchInput } from "@/components/ui/Input";
import { Pagination } from "@/components/ui/Pagination";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { formatRelative } from "@/lib/format";

const PAGE_SIZE = 25;

const AUDIENCES: { value: NotificationAudience; label: string; hint: string }[] = [
  { value: "vendor", label: "Vendor", hint: "Stock and lead time" },
  { value: "fleet_owner", label: "Fleet owner", hint: "Scheduling and cost" },
];

const STATUSES: { value: NotificationStatus; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "actioned", label: "Actioned" },
  { value: "dismissed", label: "Dismissed" },
];

const SEVERITIES: { value: NotificationSeverity; label: string; dot: string; text: string }[] = [
  { value: "critical", label: "Critical", dot: "bg-risk-red", text: "text-risk-red" },
  { value: "high", label: "High", dot: "bg-risk-amber", text: "text-risk-amber" },
  { value: "medium", label: "Medium", dot: "bg-accent", text: "text-accent" },
];

export default function AlertsPage() {
  const [params, setParams] = useSearchParams();
  const toast = useToast();

  const audience = (params.get("audience") ?? "vendor") as NotificationAudience;
  const status = (params.get("status") ?? "pending") as NotificationStatus;
  const severities = params.getAll("severity") as NotificationSeverity[];
  const customerIds = params.getAll("customer").map(Number).filter(Number.isFinite);
  const search = params.get("q") ?? "";
  const offset = Number.parseInt(params.get("offset") ?? "0", 10) || 0;
  const focusId = Number.parseInt(params.get("focus") ?? "", 10);

  const { data: customers } = useCustomers();
  const { data: scopeInfo } = useScopeInfo();
  const update = useUpdateNotification();
  const createWorkOrder = useCreateWorkOrder();
  const [converting, setConverting] = useState<number | null>(null);

  const setParam = (patch: Record<string, string | string[] | null>, keepOffset = false) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      next.delete(key);
      if (value === null || value === "") continue;
      for (const item of Array.isArray(value) ? value : [value]) next.append(key, item);
    }
    if (!keepOffset) next.delete("offset");
    setParams(next, { replace: true });
  };

  const notifications = useNotifications({
    audience: [audience],
    alert_status: [status],
    severity: severities.length ? severities : undefined,
    customer_id: customerIds.length ? customerIds : undefined,
    search: search || undefined,
    limit: PAGE_SIZE,
    offset,
  });

  // Counts for the other audience's pending queue, so switching tabs is an
  // informed choice rather than a look-and-see.
  const otherPending = useNotifications({
    audience: [audience === "vendor" ? "fleet_owner" : "vendor"],
    alert_status: ["pending"],
    limit: 1,
  });

  const setStatus = (id: number, next: NotificationStatus, verb: string) => {
    update.mutate(
      { id, status: next },
      {
        onError: (error) =>
          toast.show({
            tone: "error",
            title: `Could not ${verb} the alert`,
            detail: `${error.message} The row has been put back.`,
          }),
      },
    );
  };

  const convert = (notification: NotificationOut) => {
    setConverting(notification.id);
    createWorkOrder.mutate(
      {
        vin: notification.vin,
        part_code: notification.part_code,
        status: "draft",
        notes: `Raised from alert #${notification.id}: ${notification.title}`,
      },
      {
        onSuccess: () => {
          update.mutate({ id: notification.id, status: "actioned" });
          toast.show({
            tone: "success",
            title: "Work order raised",
            detail: `${notification.part_name} on ${notification.vin}. The alert is marked actioned.`,
          });
          setConverting(null);
        },
        onError: (error) => {
          toast.show({
            tone: "error",
            title: "Could not raise the work order",
            detail: error.message,
          });
          setConverting(null);
        },
      },
    );
  };

  return (
    <>
      <PageHeader
        title="Alerts"
        description="Every notification the scoring run produced, addressed to the person who can act on it."
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-hairline p-0.5">
          {AUDIENCES.map((entry) => (
            <button
              key={entry.value}
              type="button"
              onClick={() => setParam({ audience: entry.value })}
              aria-pressed={audience === entry.value}
              className={cn(
                "flex h-8 items-center gap-2 rounded-md px-3 text-[0.8125rem] transition-colors",
                audience === entry.value
                  ? "bg-accent-soft font-medium text-accent-ink"
                  : "text-muted hover:text-ink",
              )}
            >
              {entry.label}
              <span className="text-[0.6875rem] text-faint">{entry.hint}</span>
              {audience !== entry.value && otherPending.data ? (
                <span className="tabular rounded-full bg-canvas px-1.5 text-[0.6875rem] text-muted">
                  {otherPending.data.total}
                </span>
              ) : null}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap gap-1.5">
          {STATUSES.map((entry) => (
            <button
              key={entry.value}
              type="button"
              onClick={() => setParam({ status: entry.value })}
              className={cn(
                "rounded-full border px-2.5 py-1 text-[0.75rem] transition-colors",
                status === entry.value
                  ? "border-accent/40 bg-accent-soft text-accent-ink"
                  : "border-hairline bg-surface text-muted hover:text-ink",
              )}
            >
              {entry.label}
            </button>
          ))}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <SearchInput
            value={search}
            onValueChange={(value) => setParam({ q: value || null })}
            placeholder="VIN or component"
            className="w-56"
          />
          <FilterMenu
            label="Severity"
            options={SEVERITIES.map((entry) => ({ value: entry.value, label: entry.label }))}
            selected={severities}
            onChange={(next) => setParam({ severity: next })}
          />
          <FilterMenu
            label="Customer"
            options={(customers ?? []).map((customer) => ({
              value: customer.customer_id,
              label: customer.name,
            }))}
            selected={customerIds}
            onChange={(next) => setParam({ customer: next.map(String) })}
          />
        </div>
      </div>

      {notifications.isError ? (
        <Card>
          <ErrorState error={notifications.error} onRetry={() => void notifications.refetch()} />
        </Card>
      ) : notifications.isPending ? (
        <div className="space-y-2.5">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="h-[5.5rem] w-full rounded-card" />
          ))}
        </div>
      ) : notifications.data.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={BellOff}
            title={`Nothing ${status} for the ${audience === "vendor" ? "vendor" : "fleet owner"}`}
            description={
              status === "pending"
                ? "Every alert in this queue has been dealt with. New ones appear here after the next scoring run."
                : "No alert in this scope has that status with the filters applied."
            }
            action={
              status !== "pending" ? (
                <Button onClick={() => setParam({ status: "pending" })}>Show pending</Button>
              ) : null
            }
          />
        </Card>
      ) : (
        <>
          <ul className="space-y-2.5">
            {notifications.data.items.map((notification) => (
              <AlertRow
                key={notification.id}
                notification={notification}
                focused={notification.id === focusId}
                canWrite={scopeInfo?.can_write ?? false}
                converting={converting === notification.id}
                onAcknowledge={() => setStatus(notification.id, "acknowledged", "acknowledge")}
                onDismiss={() => setStatus(notification.id, "dismissed", "dismiss")}
                onReopen={() => setStatus(notification.id, "pending", "reopen")}
                onConvert={() => convert(notification)}
              />
            ))}
          </ul>

          <Pagination
            className="mt-3"
            total={notifications.data.total}
            limit={PAGE_SIZE}
            offset={offset}
            noun="alerts"
            onOffsetChange={(next) => setParam({ offset: String(next) }, true)}
          />
        </>
      )}
    </>
  );
}

function AlertRow({
  notification,
  focused,
  canWrite,
  converting,
  onAcknowledge,
  onDismiss,
  onReopen,
  onConvert,
}: {
  notification: NotificationOut;
  focused: boolean;
  canWrite: boolean;
  converting: boolean;
  onAcknowledge: () => void;
  onDismiss: () => void;
  onReopen: () => void;
  onConvert: () => void;
}) {
  const severity = SEVERITIES.find((entry) => entry.value === notification.severity);
  const ref = useRef<HTMLLIElement>(null);

  // The bell links to a specific alert; bring it into view rather than making
  // the reader hunt for it.
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focused]);

  const isOpen = notification.status === "pending";

  return (
    <li
      ref={ref}
      className={cn(
        "rounded-card border bg-surface px-4 py-3.5 transition-colors",
        focused ? "border-accent/50 bg-accent-soft/40" : "border-hairline",
      )}
    >
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <span
          className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", severity?.dot ?? "bg-faint")}
          aria-hidden="true"
        />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2.5">
            <h3 className="text-[0.875rem] font-medium text-ink">{notification.title}</h3>
            <span className={cn("text-[0.6875rem] uppercase tracking-wide", severity?.text)}>
              {severity?.label ?? notification.severity}
            </span>
            {notification.status !== "pending" ? (
              <span className="rounded-full bg-canvas px-2 py-0.5 text-[0.6875rem] text-muted">
                {notification.status}
              </span>
            ) : null}
          </div>

          <p className="mt-1 text-[0.8125rem] leading-5 text-muted">{notification.message}</p>

          <p className="mt-1.5 text-[0.75rem] text-faint">
            <Link
              to={`/fleet/${notification.vin}?part=${notification.part_code}`}
              className="text-accent transition-colors hover:text-accent-ink"
            >
              {notification.vin}
            </Link>{" "}
            - {notification.part_name} - {notification.customer_name} -{" "}
            {formatRelative(notification.created_at)}
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          {isOpen ? (
            <>
              <Button
                size="sm"
                icon={Check}
                onClick={onAcknowledge}
                disabled={!canWrite}
                title={canWrite ? "Mark as seen" : "This view is read-only"}
              >
                Acknowledge
              </Button>
              <Button
                size="sm"
                icon={X}
                onClick={onDismiss}
                disabled={!canWrite}
                title={canWrite ? "Not worth acting on" : "This view is read-only"}
              >
                Dismiss
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              icon={Undo2}
              onClick={onReopen}
              disabled={!canWrite}
              title={canWrite ? "Put it back in the pending queue" : "This view is read-only"}
            >
              Reopen
            </Button>
          )}
          <Button
            size="sm"
            variant="primary"
            icon={ClipboardList}
            onClick={onConvert}
            loading={converting}
            disabled={!canWrite || notification.status === "actioned"}
            title={
              notification.status === "actioned"
                ? "A work order has already been raised from this alert"
                : "Raise a draft work order and mark this actioned"
            }
          >
            Work order
          </Button>
        </div>
      </div>
    </li>
  );
}
