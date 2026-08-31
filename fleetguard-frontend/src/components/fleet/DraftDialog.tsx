/**
 * "Draft outreach" - the Action Agent, in a panel.
 *
 * The important part of this screen is not the message; it is the facts panel
 * under it. `POST /api/chat/draft` gathers its facts in Python and hands the
 * model those facts **with no tools at all**, then returns them alongside the
 * text. Showing both side by side is what lets a reviewer check every number
 * in the message against exactly what the model was given, which is a stronger
 * claim than "the prompt asks it not to make things up".
 *
 * Nothing is sent anywhere. The draft is for a person to copy, edit and send.
 */

import { Check, Copy, Mail, Truck } from "lucide-react";
import { useEffect, useState } from "react";

import { useDraftMessage } from "@/api/queries";
import type { NotificationAudience } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Drawer";
import { ErrorState } from "@/components/ui/EmptyState";
import { Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { humanise } from "@/lib/format";

interface DraftDialogProps {
  open: boolean;
  onClose: () => void;
  vin: string;
  partCode: string;
  partName: string;
}

const AUDIENCES: { value: NotificationAudience; label: string; hint: string; icon: typeof Mail }[] = [
  {
    value: "vendor",
    label: "Parts vendor",
    hint: "Commit stock against the lead time",
    icon: Truck,
  },
  {
    value: "fleet_owner",
    label: "Fleet owner",
    hint: "Book the slot and avoid the roadside cost",
    icon: Mail,
  },
];

export function DraftDialog({ open, onClose, vin, partCode, partName }: DraftDialogProps) {
  const [audience, setAudience] = useState<NotificationAudience>("fleet_owner");
  const [copied, setCopied] = useState(false);
  const draft = useDraftMessage();
  const toast = useToast();

  // Each audience is a separate request; switching while a draft is on screen
  // must not leave the previous audience's text under the new label.
  useEffect(() => {
    if (!open) return;
    draft.mutate({ vin, part: partCode, audience });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, vin, partCode, audience]);

  const copy = async () => {
    if (!draft.data) return;
    try {
      await navigator.clipboard.writeText(draft.data.message);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.show({
        tone: "error",
        title: "Could not copy",
        detail: "The browser refused clipboard access. Select the text and copy it manually.",
      });
    }
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Draft outreach"
      subtitle={`${partName} on ${vin}`}
      width="lg"
      footer={
        <>
          <p className="mr-auto text-[0.75rem] text-muted">
            Nothing is sent. Copy it into your own mail or ticket.
          </p>
          <Button
            icon={copied ? Check : Copy}
            onClick={copy}
            disabled={!draft.data}
            variant="primary"
          >
            {copied ? "Copied" : "Copy message"}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <div className="flex gap-2">
          {AUDIENCES.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setAudience(option.value)}
              aria-pressed={audience === option.value}
              className={cn(
                "flex flex-1 flex-col gap-0.5 rounded-card border px-3.5 py-2.5 text-left transition-colors",
                audience === option.value
                  ? "border-accent/40 bg-accent-soft"
                  : "border-hairline bg-surface hover:bg-canvas",
              )}
            >
              <span
                className={cn(
                  "flex items-center gap-1.5 text-[0.8125rem] font-medium",
                  audience === option.value ? "text-accent-ink" : "text-ink",
                )}
              >
                <option.icon className="h-3.5 w-3.5" aria-hidden="true" />
                {option.label}
              </span>
              <span className="text-[0.75rem] text-muted">{option.hint}</span>
            </button>
          ))}
        </div>

        {draft.isPending ? (
          <div className="space-y-3">
            <Skeleton className="h-3 w-40" />
            <SkeletonText lines={6} />
          </div>
        ) : draft.isError ? (
          <ErrorState
            error={draft.error}
            onRetry={() => draft.mutate({ vin, part: partCode, audience })}
          />
        ) : draft.data ? (
          <>
            <article className="whitespace-pre-wrap rounded-card border border-hairline bg-canvas px-4 py-3.5 text-[0.8125rem] leading-6 text-ink">
              {draft.data.message}
            </article>

            {draft.data.truncated ? (
              <p className="text-[0.75rem] text-risk-amber">
                The model ran out of output tokens, so this draft stops early.
              </p>
            ) : null}

            <section>
              <h3 className="text-[0.8125rem] font-medium text-ink">
                Every fact the model was given
              </h3>
              <p className="mt-0.5 text-[0.75rem] leading-5 text-muted">
                It had no tools, so it had nothing else. Anything in the message that is not
                in this list would be invented - which is what makes the claim checkable.
              </p>
              <dl className="mt-3 divide-y divide-hairline rounded-card border border-hairline">
                {Object.entries(draft.data.facts).map(([key, value]) => (
                  <div key={key} className="flex gap-4 px-3.5 py-2">
                    <dt className="w-44 shrink-0 text-[0.75rem] text-muted">{humanise(key)}</dt>
                    <dd className="tabular min-w-0 flex-1 break-words text-[0.75rem] text-ink">
                      {formatFact(value)}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          </>
        ) : null}
      </div>
    </Drawer>
  );
}

function formatFact(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.map((item) => formatFact(item)).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
