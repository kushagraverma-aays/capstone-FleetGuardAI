/**
 * The assistant, as a panel that is available from every screen.
 *
 * Two shapes, one conversation. On a wide screen the panel docks beside the
 * content, because the questions worth asking are about the screen you are
 * looking at - "why is this one red?" is a poor question if answering it hides
 * the row. Below `xl` there is no room for both, so it becomes the same modal
 * drawer every other overlay in the product uses, with its focus trap.
 *
 * The empty state is doing real work: it says where the answers come from,
 * lists what the assistant can look up, and offers the questions the API says
 * it answers well. A chat box with a blinking cursor and no suggestions is a
 * demo that only works if you already know what to type.
 */

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowUp, ChevronDown, PlugZap, RotateCcw, Sparkles, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { Conversation } from "./Conversation";
import { useChatCapabilities, useCustomers, useScopeInfo } from "@/api/queries";
import { IconButton } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Drawer";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";
import { humanise } from "@/lib/format";
import { transitions } from "@/lib/motion";
import { WIDE_SCREEN, useMediaQuery } from "@/lib/useMediaQuery";
import { useAssistant } from "@/state/assistant";
import { useScope } from "@/state/session";

/** The API caps a question at 2000 characters; the field says so before the
 *  server has to. */
const MAX_QUESTION = 2000;

const PANEL_WIDTH = "27rem";

export function AssistantPanel() {
  const { open, closePanel } = useAssistant();
  const wide = useMediaQuery(WIDE_SCREEN);
  const reduced = useReducedMotion();

  if (wide) {
    return (
      <AnimatePresence initial={false}>
        {open ? (
          <motion.aside
            aria-label="Fleet assistant"
            initial={reduced ? { opacity: 0 } : { width: 0, opacity: 0 }}
            animate={reduced ? { opacity: 1 } : { width: PANEL_WIDTH, opacity: 1 }}
            exit={reduced ? { opacity: 0 } : { width: 0, opacity: 0 }}
            transition={transitions.base}
            style={reduced ? { width: PANEL_WIDTH } : undefined}
            onKeyDown={(event) => {
              if (event.key === "Escape") closePanel();
            }}
            className="relative shrink-0 overflow-hidden border-l border-hairline bg-surface"
          >
            {/* A fixed inner width, so the conversation does not re-wrap on
                every frame while the panel animates open. */}
            <div className="flex h-full flex-col" style={{ width: PANEL_WIDTH }}>
              <PanelHeader onClose={closePanel} />
              <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 py-4">
                <PanelContent />
              </div>
              <div className="border-t border-hairline px-4 py-3">
                <PanelComposer />
              </div>
            </div>
          </motion.aside>
        ) : null}
      </AnimatePresence>
    );
  }

  return (
    <Drawer
      open={open}
      onClose={closePanel}
      title="Assistant"
      subtitle={<ScopeLine />}
      width="md"
      headerAction={<ResetConversationButton />}
      footer={<PanelComposer className="w-full" />}
    >
      <PanelContent />
    </Drawer>
  );
}

function ScopeLine() {
  const scope = useScope();
  const { data: customers } = useCustomers();
  const { data: scopeInfo } = useScopeInfo();

  if (scope === "all") return <>Answering across all customers</>;

  const name =
    customers?.find((customer) => customer.customer_id === scope)?.name ??
    scopeInfo?.customer_name ??
    "this customer";
  return <>Answering about {name} only</>;
}

function PanelHeader({ onClose }: { onClose: () => void }) {
  return (
    <header className="flex items-start gap-2 border-b border-hairline px-4 py-3">
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-soft">
        <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <h2 className="text-[0.9375rem] font-medium text-ink">Assistant</h2>
        <p className="truncate text-[0.75rem] text-muted">
          <ScopeLine />
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <ResetConversationButton />
        <IconButton icon={X} label="Close the assistant" size="sm" onClick={onClose} />
      </div>
    </header>
  );
}

/** Empties the transcript. Disabled rather than hidden when there is nothing
 *  to clear, so the control does not appear and disappear as you talk. */
function ResetConversationButton() {
  const { turns, reset, pendingQuestion } = useAssistant();

  return (
    <IconButton
      icon={RotateCcw}
      label="Start a new conversation"
      size="sm"
      onClick={reset}
      disabled={turns.length === 0 && pendingQuestion === null}
    />
  );
}

/** Everything above the composer: the transcript, or the state that explains
 *  why there isn't one. */
function PanelContent() {
  const { turns, pendingQuestion, ask, retry, clearedByScopeChange } = useAssistant();
  const capabilities = useChatCapabilities();
  const contentRef = useStickToBottom();

  const empty = turns.length === 0 && pendingQuestion === null;

  return (
    <div ref={contentRef}>
      {clearedByScopeChange ? (
        <p className="mb-4 rounded-lg border border-hairline bg-canvas px-3 py-2 text-[0.75rem] leading-5 text-muted">
          The customer scope changed, so this conversation was cleared. Its answers were about the
          fleet you were looking at before.
        </p>
      ) : null}

      {capabilities.isPending ? (
        <div className="space-y-3">
          <Skeleton className="h-4 w-36" />
          <SkeletonText lines={3} />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-4/5" />
        </div>
      ) : capabilities.isError ? (
        <ErrorState error={capabilities.error} onRetry={() => capabilities.refetch()} compact />
      ) : capabilities.data && !capabilities.data.available ? (
        <EmptyState
          icon={PlugZap}
          compact
          title="The assistant is not configured"
          description="Set LLM_API_KEY in the API environment and restart it. Nothing else on this dashboard depends on the model - every other screen still works."
        />
      ) : empty ? (
        <EmptyPanel onPick={ask} />
      ) : (
        <Conversation turns={turns} pendingQuestion={pendingQuestion} onRetry={retry} />
      )}
    </div>
  );
}

/** Keeps the newest answer in view while it reveals.
 *
 *  The reply is written into the transcript a few words at a time over about a
 *  second, so the box keeps growing after the message has been added - one
 *  scroll on arrival would leave the end of a long answer below the fold. A
 *  `ResizeObserver` follows the growth instead. It only follows a reader who
 *  was already at the bottom: pulling someone back down while they re-read an
 *  earlier answer is worse than letting the new one arrive off screen.
 */
function useStickToBottom() {
  const contentRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const content = contentRef.current;
    const scroller = findScrollParent(content);
    if (!content || !scroller) return;

    let pinned = true;
    const onScroll = () => {
      pinned = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });

    const observer = new ResizeObserver(() => {
      if (pinned) scroller.scrollTop = scroller.scrollHeight;
    });
    observer.observe(content);

    return () => {
      scroller.removeEventListener("scroll", onScroll);
      observer.disconnect();
    };
  }, []);

  return contentRef;
}

function findScrollParent(element: HTMLElement | null): HTMLElement | null {
  let node = element?.parentElement ?? null;
  while (node) {
    const overflow = window.getComputedStyle(node).overflowY;
    if (overflow === "auto" || overflow === "scroll") return node;
    node = node.parentElement;
  }
  return null;
}

function EmptyPanel({ onPick }: { onPick: (question: string) => void }) {
  const { data } = useChatCapabilities();
  const [toolsOpen, setToolsOpen] = useState(false);
  const reduced = useReducedMotion();

  if (!data) return null;

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-[0.9375rem] font-medium text-ink">Ask about this fleet</h3>
        <p className="mt-1 text-[0.8125rem] leading-5 text-muted">{data.grounding}</p>
      </div>

      <div>
        <p className="text-label font-medium uppercase tracking-wider text-faint">
          Try one of these
        </p>
        <div className="mt-2 flex flex-col items-start gap-1.5">
          {data.suggested_questions.map((question) => (
            <button
              key={question}
              type="button"
              onClick={() => onPick(question)}
              className={cn(
                "rounded-full border border-hairline bg-surface px-3.5 py-1.5 text-left",
                "text-[0.8125rem] leading-5 text-ink transition-colors",
                "hover:border-accent/40 hover:bg-accent-soft hover:text-accent-ink",
              )}
            >
              {question}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-card border border-hairline">
        <button
          type="button"
          onClick={() => setToolsOpen((value) => !value)}
          aria-expanded={toolsOpen}
          className="flex w-full items-center justify-between gap-2 px-3.5 py-2.5 text-left"
        >
          <span className="text-[0.8125rem] text-ink">
            What it can look up
            <span className="tabular ml-1.5 text-[0.75rem] text-faint">{data.tools.length}</span>
          </span>
          <ChevronDown
            className={cn(
              "h-3.5 w-3.5 shrink-0 text-faint transition-transform",
              toolsOpen && "rotate-180",
            )}
            aria-hidden="true"
          />
        </button>

        <AnimatePresence initial={false}>
          {toolsOpen ? (
            <motion.div
              initial={reduced ? { opacity: 0 } : { height: 0, opacity: 0 }}
              animate={reduced ? { opacity: 1 } : { height: "auto", opacity: 1 }}
              exit={reduced ? { opacity: 0 } : { height: 0, opacity: 0 }}
              transition={transitions.quick}
              className="overflow-hidden"
            >
              <ul className="divide-y divide-hairline border-t border-hairline">
                {data.tools.map((tool) => (
                  <li key={tool.name} className="px-3.5 py-2.5">
                    <p className="text-[0.75rem] font-medium text-ink">{humanise(tool.name)}</p>
                    <p className="mt-0.5 text-[0.75rem] leading-5 text-muted">{tool.description}</p>
                  </li>
                ))}
              </ul>
              <p className="border-t border-hairline px-3.5 py-2 text-[0.6875rem] text-faint">
                {data.model} · up to {data.max_tool_rounds} tool rounds per answer
              </p>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </div>
  );
}

function PanelComposer({ className }: { className?: string }) {
  const { ask, pendingQuestion, open } = useAssistant();
  const capabilities = useChatCapabilities();
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const busy = pendingQuestion !== null;
  const disabled = capabilities.isPending || capabilities.isError;

  // The field grows with the question up to about five lines, then scrolls.
  useLayoutEffect(() => {
    const field = inputRef.current;
    if (!field) return;
    field.style.height = "auto";
    field.style.height = `${Math.min(field.scrollHeight, 120)}px`;
  }, [value]);

  // After the drawer has moved focus to its own panel, not before.
  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => inputRef.current?.focus(), 80);
    return () => window.clearTimeout(timer);
  }, [open]);

  if (capabilities.data && !capabilities.data.available) return null;

  const submit = () => {
    const question = value.trim();
    if (!question || busy || disabled) return;
    ask(question);
    setValue("");
  };

  const remaining = MAX_QUESTION - value.length;

  return (
    <div className={className}>
      <div
        className={cn(
          "flex items-end gap-2 rounded-card border border-hairline bg-surface px-2.5 py-2",
          "transition-colors focus-within:border-accent/60",
        )}
      >
        <textarea
          ref={inputRef}
          rows={1}
          value={value}
          maxLength={MAX_QUESTION}
          disabled={disabled}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder={busy ? "Waiting for the last answer" : "Ask about risk, cost or a VIN"}
          aria-label="Ask the assistant a question"
          className={cn(
            "scroll-thin max-h-[120px] flex-1 resize-none bg-transparent",
            "text-[0.8125rem] leading-6 text-ink outline-none placeholder:text-faint",
          )}
        />
        <IconButton
          icon={ArrowUp}
          label="Send question"
          variant="primary"
          size="sm"
          onClick={submit}
          disabled={value.trim().length === 0 || busy || disabled}
        />
      </div>

      <p className="mt-1.5 flex items-center justify-between gap-2 px-0.5 text-[0.6875rem] text-faint">
        <span>Enter to send · Shift + Enter for a new line</span>
        {remaining < 200 ? <span className="tabular">{remaining} left</span> : null}
      </p>
    </div>
  );
}
