/**
 * Empty and error states.
 *
 * Spec 9: every one gets an icon, a sentence explaining what happened, and an
 * action. "No data" on its own tells an operator nothing about whether the
 * fleet is healthy, their filter is too narrow, or the backend is down - and
 * those three need three different sentences, which is why `ErrorState` reads
 * the error slug rather than printing whatever the server said.
 */

import { AlertCircle, Inbox, RefreshCw, ShieldOff, WifiOff, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "./Button";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/cn";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  /** What happened and what to do about it, in a sentence. */
  description: ReactNode;
  action?: ReactNode;
  className?: string;
  compact?: boolean;
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  className,
  compact = false,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "px-6 py-10" : "px-6 py-16",
        className,
      )}
    >
      <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-hairline bg-canvas">
        <Icon className="h-5 w-5 text-muted" aria-hidden="true" />
      </span>
      <h3 className="mt-4 text-[0.9375rem] font-medium text-ink">{title}</h3>
      <p className="mt-1.5 max-w-md text-[0.8125rem] leading-5 text-muted">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

interface ErrorStateProps {
  error: unknown;
  /** Wired to the query's `refetch`. Omitted for errors retrying cannot fix. */
  onRetry?: () => void;
  className?: string;
  compact?: boolean;
}

interface Explained {
  icon: LucideIcon;
  title: string;
  description: string;
  retryable: boolean;
}

/** Turns an error into words an operator can act on. Branches on the slug -
 *  never on the sentence, which is written for a person and may change. */
function explain(error: unknown): Explained {
  if (error instanceof ApiError) {
    switch (error.slug) {
      case "network_error":
        return {
          icon: WifiOff,
          title: "Cannot reach the FleetGuard API",
          description:
            "The request never left the browser. Check that the backend is running and reachable, then try again.",
          retryable: true,
        };
      case "forbidden":
        return {
          icon: ShieldOff,
          title: "Not available in this view",
          description:
            error.message ||
            "This action belongs to the manufacturer view. Switch scope to continue.",
          retryable: false,
        };
      case "not_found":
        return {
          icon: AlertCircle,
          title: "Nothing here",
          description: error.message || "That record does not exist in the current scope.",
          retryable: false,
        };
      case "invalid_request":
        return {
          icon: AlertCircle,
          title: "That request was not valid",
          description:
            error.problems.length > 0
              ? error.problems
                  .map((problem) => `${problem.field}: ${problem.problem}`)
                  .join("; ")
              : error.message,
          retryable: false,
        };
      case "unauthenticated":
        return {
          icon: ShieldOff,
          title: "Sign in again",
          description:
            error.message || "This session is no longer valid. Sign in to continue.",
          retryable: false,
        };
      case "llm_unavailable":
        return {
          icon: AlertCircle,
          title: "The assistant is offline",
          description:
            "The language model provider could not be reached. Every other screen still works - the dashboard does not depend on it.",
          retryable: true,
        };
      case "llm_busy":
        return {
          icon: AlertCircle,
          title: "The assistant is busy",
          description:
            "This minute's allowance of language model capacity is spent. Wait a few seconds and ask again - nothing is broken.",
          retryable: true,
        };
      case "rate_limited":
        return {
          icon: AlertCircle,
          title: "Too many requests",
          description: "The assistant is rate limited to protect its budget. Wait a moment and ask again.",
          retryable: true,
        };
      default:
        return {
          icon: AlertCircle,
          title: "Something went wrong",
          description: error.message || "The server could not complete the request.",
          retryable: error.isRetryable,
        };
    }
  }

  return {
    icon: AlertCircle,
    title: "Something went wrong",
    description:
      error instanceof Error ? error.message : "An unexpected error stopped this from loading.",
    retryable: true,
  };
}

export function ErrorState({ error, onRetry, className, compact }: ErrorStateProps) {
  const { icon, title, description, retryable } = explain(error);
  const requestId = error instanceof ApiError ? error.requestId : null;

  return (
    <EmptyState
      icon={icon}
      title={title}
      description={
        <>
          {description}
          {requestId ? (
            <span className="mt-2 block font-mono text-[0.6875rem] text-faint">
              Request {requestId}
            </span>
          ) : null}
        </>
      }
      action={
        retryable && onRetry ? (
          <Button icon={RefreshCw} onClick={onRetry}>
            Try again
          </Button>
        ) : null
      }
      className={className}
      compact={compact}
    />
  );
}
