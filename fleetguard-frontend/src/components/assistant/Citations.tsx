/**
 * The citation chips under every reply.
 *
 * This is the part of the assistant that makes the grounding claim checkable
 * instead of asserted. `POST /api/chat` returns `data_cited`: one entry per
 * tool call, with the arguments the loop chose and the raw JSON that came
 * back. Expanding a chip shows exactly that JSON, so a reader can find the
 * figure quoted in the answer sitting in the data it came from - or find that
 * it isn't there.
 *
 * Spec 9 is explicit that this transparency is a differentiator and must not
 * be hidden, so the chips are always visible; only the JSON is behind a click.
 */

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Check, ChevronDown, Copy, Database } from "lucide-react";
import { useState } from "react";

import type { Citation } from "@/api/types";
import { cn } from "@/lib/cn";
import { humanise } from "@/lib/format";
import { transitions } from "@/lib/motion";

/** The arguments a tool was called with, as one readable line. An empty object
 *  means the loop called it with no narrowing, which is worth saying in words
 *  rather than showing as `{}`. */
function describeArguments(args: Record<string, unknown>): string {
  const entries = Object.entries(args).filter(([, value]) => {
    if (value === null || value === undefined || value === "") return false;
    // `{parts: []}` is the loop saying "all of them", which reads as an empty
    // label rather than as an argument worth printing.
    if (Array.isArray(value) && value.length === 0) return false;
    return true;
  });
  if (entries.length === 0) return "no arguments - the whole scope";
  return entries
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
    .join("  ·  ");
}

/** Enough colour to read the shape of a JSON document at a glance: keys quiet,
 *  strings in ink, figures in the accent. Not a syntax highlighter. */
function JsonBlock({ value }: { value: unknown }) {
  const text = JSON.stringify(value, null, 2);
  const parts = text.split(
    /("(?:\\.|[^"\\])*"\s*:|"(?:\\.|[^"\\])*"|-?\d+\.?\d*|\btrue\b|\bfalse\b|\bnull\b)/g,
  );

  return (
    <pre className="scroll-thin max-h-72 overflow-auto px-3 py-2.5 font-mono text-[0.6875rem] leading-5">
      {parts.map((part, index) => {
        if (!part) return null;
        if (index % 2 === 0) return <span key={index} className="text-faint">{part}</span>;
        if (part.endsWith(":")) {
          return (
            <span key={index} className="text-muted">
              {part}
            </span>
          );
        }
        if (part.startsWith('"')) {
          return (
            <span key={index} className="text-ink">
              {part}
            </span>
          );
        }
        return (
          <span key={index} className="tabular text-accent-ink">
            {part}
          </span>
        );
      })}
    </pre>
  );
}

function CitationCard({ citation }: { citation: Citation }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(citation.result, null, 2));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* The block is selectable; a browser that refuses the clipboard still
         leaves the reader able to copy it by hand. */
    }
  };

  return (
    <div className="mt-2 overflow-hidden rounded-lg border border-hairline bg-surface">
      <div className="flex items-start justify-between gap-3 border-b border-hairline px-3 py-2">
        <div className="min-w-0">
          <p className="font-mono text-[0.6875rem] text-muted">{citation.tool}</p>
          <p className="mt-0.5 break-words text-[0.6875rem] text-faint">
            {describeArguments(citation.arguments)}
          </p>
        </div>
        <button
          type="button"
          onClick={copy}
          className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-[0.6875rem] text-muted transition-colors hover:bg-canvas hover:text-ink"
        >
          {copied ? (
            <Check className="h-3 w-3" aria-hidden="true" />
          ) : (
            <Copy className="h-3 w-3" aria-hidden="true" />
          )}
          {copied ? "Copied" : "Copy JSON"}
        </button>
      </div>
      <JsonBlock value={citation.result} />
    </div>
  );
}

export function Citations({ citations }: { citations: Citation[] }) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const reduced = useReducedMotion();

  if (citations.length === 0) return null;

  return (
    <section className="mt-2.5">
      <p className="mb-1.5 flex items-center gap-1.5 text-[0.6875rem] text-faint">
        <Database className="h-3 w-3" aria-hidden="true" />
        {citations.length === 1
          ? "Built from 1 lookup against your data"
          : `Built from ${citations.length} lookups against your data`}
      </p>

      <div className="flex flex-wrap gap-1.5">
        {citations.map((citation, index) => {
          const open = openIndex === index;
          return (
            <button
              key={`${citation.tool}-${index}`}
              type="button"
              onClick={() => setOpenIndex(open ? null : index)}
              aria-expanded={open}
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[0.6875rem] transition-colors",
                open
                  ? "border-accent/40 bg-accent-soft text-accent-ink"
                  : "border-hairline bg-surface text-muted hover:bg-canvas hover:text-ink",
              )}
            >
              <span>{humanise(citation.tool)}</span>
              <span className="tabular text-faint">{Math.round(citation.duration_ms)} ms</span>
              <ChevronDown
                className={cn("h-3 w-3 transition-transform", open && "rotate-180")}
                aria-hidden="true"
              />
            </button>
          );
        })}
      </div>

      <AnimatePresence initial={false} mode="wait">
        {openIndex !== null ? (
          <motion.div
            key={openIndex}
            initial={reduced ? { opacity: 0 } : { opacity: 0, height: 0 }}
            animate={reduced ? { opacity: 1 } : { opacity: 1, height: "auto" }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, height: 0 }}
            transition={transitions.quick}
            className="overflow-hidden"
          >
            <CitationCard citation={citations[openIndex]} />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}
