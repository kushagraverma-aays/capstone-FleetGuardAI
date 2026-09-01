/**
 * The transcript.
 *
 * `POST /api/chat` answers in one shot - the tool-calling loop has to finish
 * before there is anything true to show - so there is no token stream to
 * render. What the panel does instead is reveal the finished reply
 * progressively, which is what spec 9 asks for by "streaming-feel": the answer
 * arrives the way a person reads it rather than appearing as a wall. It is
 * capped at under a second, and `prefers-reduced-motion` skips it entirely.
 *
 * Nothing about the reveal is a claim about progress. While the request is out
 * the panel says it is working and counts the seconds it has been waiting; it
 * does not narrate tool calls it cannot see.
 */

import { motion, useReducedMotion } from "framer-motion";
import { AlertCircle, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Citations } from "./Citations";
import { Markdown } from "./Markdown";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { entrance } from "@/lib/motion";
import type { AssistantTurn, FailedTurn, Turn, UserTurn } from "@/state/assistant";

/** Reveals `text` a few words at a time, in about 0.7s whatever the length.
 *  Only ever runs once per message: `enabled` is captured by the caller when
 *  the turn first mounts, so a re-render never replays it. */
function useProgressiveReveal(text: string, enabled: boolean): { shown: string; done: boolean } {
  const [length, setLength] = useState(enabled ? 0 : text.length);

  useEffect(() => {
    if (!enabled) {
      setLength(text.length);
      return;
    }

    const STEPS = 26;
    const step = Math.max(3, Math.ceil(text.length / STEPS));
    let shown = 0;

    const timer = window.setInterval(() => {
      shown = Math.min(text.length, shown + step);
      // Land on a word boundary so the reveal never stops mid-word.
      if (shown < text.length) {
        const nextSpace = text.indexOf(" ", shown);
        if (nextSpace > -1 && nextSpace - shown < 12) shown = nextSpace;
      }
      setLength(shown);
      if (shown >= text.length) window.clearInterval(timer);
    }, 28);

    return () => window.clearInterval(timer);
  }, [text, enabled]);

  return { shown: text.slice(0, length), done: length >= text.length };
}

function Bubble({
  children,
  className,
  animate = true,
  ariaHidden = false,
}: {
  children: ReactNode;
  className?: string;
  animate?: boolean;
  ariaHidden?: boolean;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      variants={entrance(reduced)}
      initial={animate ? "hidden" : false}
      animate={animate ? "visible" : undefined}
      aria-hidden={ariaHidden || undefined}
      className={className}
    >
      {children}
    </motion.div>
  );
}

function UserBubble({ turn }: { turn: UserTurn }) {
  return (
    <Bubble className="flex justify-end">
      <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-[0.8125rem] leading-6 text-white">
        {turn.text}
      </p>
    </Bubble>
  );
}

function ReplyBubble({ turn, fresh }: { turn: AssistantTurn; fresh: boolean }) {
  const reduced = useReducedMotion();
  // Captured once: if this turn re-renders because a later message arrived,
  // the reveal must not start again from nothing.
  const [reveal] = useState(fresh && !reduced);
  const { shown, done } = useProgressiveReveal(turn.text, reveal);

  return (
    <Bubble className="max-w-full">
      <Markdown>{shown}</Markdown>

      {done ? (
        <>
          {turn.truncated ? (
            <p className="mt-2 text-[0.75rem] text-risk-amber">
              The model ran out of output tokens, so this answer stops early. Ask a narrower
              question to get a complete one.
            </p>
          ) : null}

          {turn.hitRoundLimit ? (
            <p className="mt-2 text-[0.75rem] text-risk-amber">
              The tool budget ran out, so this was written from what had been gathered by then.
              It may be incomplete.
            </p>
          ) : null}

          {turn.citations.length === 0 ? (
            <p className="mt-2 text-[0.6875rem] text-faint">
              No lookups were needed for this answer, so there is nothing to cite.
            </p>
          ) : (
            <Citations citations={turn.citations} />
          )}
        </>
      ) : null}
    </Bubble>
  );
}

function ErrorBubble({ turn, onRetry }: { turn: FailedTurn; onRetry: () => void }) {
  const error = turn.error;
  const slug = error instanceof ApiError ? error.slug : "";

  // Branch on the slug, never on the sentence - the same rule `ErrorState`
  // follows, so the two describe an outage the same way.
  const message =
    slug === "llm_busy"
      ? "This minute's allowance of language model capacity is spent. Wait a few seconds and ask again - nothing is broken."
      : slug === "rate_limited"
        ? "The assistant is rate limited to protect its budget. Wait a moment and ask again."
      : slug === "llm_unavailable"
        ? "The language model provider could not be reached. Every other screen still works - none of them depend on it."
        : slug === "network_error"
          ? "The request never left the browser. Check that the backend is running, then ask again."
          : error instanceof ApiError
            ? error.message
            : "The question could not be answered. Try again.";

  return (
    <Bubble className="rounded-card border border-risk-red/25 bg-risk-red-soft px-3.5 py-3">
      <p className="flex items-center gap-1.5 text-[0.8125rem] font-medium text-risk-red">
        <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
        That question was not answered
      </p>
      <p className="mt-1 text-[0.75rem] leading-5 text-ink">{message}</p>
      <div className="mt-2.5">
        <Button icon={RefreshCw} size="sm" onClick={onRetry}>
          Ask again
        </Button>
      </div>
    </Bubble>
  );
}

/** The wait. Honest about what it knows: that it is working, and for how long
 *  - the tool rounds are not observable from here. */
function Thinking() {
  const [seconds, setSeconds] = useState(0);
  const reduced = useReducedMotion();

  useEffect(() => {
    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <Bubble
      className="flex items-center gap-2 text-[0.8125rem] text-muted"
      // The wait is announced by the transcript's status line, so a screen
      // reader does not hear the same sentence from two places.
      ariaHidden
    >
      <Sparkles
        className={cn("h-3.5 w-3.5 text-accent", !reduced && "animate-pulse")}
        aria-hidden="true"
      />
      <span>Reading your fleet data</span>
      {seconds >= 3 ? <span className="tabular text-[0.75rem] text-faint">{seconds}s</span> : null}
    </Bubble>
  );
}

interface ConversationProps {
  turns: Turn[];
  pendingQuestion: string | null;
  onRetry: (turnId: string) => void;
}

export function Conversation({ turns, pendingQuestion, onRetry }: ConversationProps) {
  // Only the newest reply plays the reveal; scrolling back through the
  // transcript should not re-animate answers already read.
  const newestReplyId = useMemo(() => {
    for (let index = turns.length - 1; index >= 0; index -= 1) {
      if (turns[index].role === "assistant") return turns[index].id;
    }
    return null;
  }, [turns]);

  const seenReplies = useRef<Set<string>>(new Set());
  const isFresh = (id: string) => {
    if (id !== newestReplyId) return false;
    if (seenReplies.current.has(id)) return false;
    seenReplies.current.add(id);
    return true;
  };

  // One status line for the whole transcript rather than a live region around
  // the answers themselves: the reply is written in a few words at a time, and
  // a live region would read every one of those steps out loud.
  const status = statusLine(turns, pendingQuestion);

  return (
    <div className="space-y-4">
      <p className="sr-only" role="status" aria-live="polite">
        {status}
      </p>

      {turns.map((turn) => {
        if (turn.role === "user") return <UserBubble key={turn.id} turn={turn} />;
        if (turn.role === "error")
          return <ErrorBubble key={turn.id} turn={turn} onRetry={() => onRetry(turn.id)} />;
        return <ReplyBubble key={turn.id} turn={turn} fresh={isFresh(turn.id)} />;
      })}

      {pendingQuestion !== null ? <Thinking /> : null}
    </div>
  );
}

function statusLine(turns: Turn[], pendingQuestion: string | null): string {
  if (pendingQuestion !== null) return "Reading your fleet data.";

  const last = turns[turns.length - 1];
  if (!last) return "";
  if (last.role === "error") return "That question was not answered.";
  if (last.role !== "assistant") return "";
  const count = last.citations.length;
  if (count === 0) return "Answer ready. No lookups were needed.";
  return `Answer ready, built from ${count} ${count === 1 ? "lookup" : "lookups"}.`;
}
