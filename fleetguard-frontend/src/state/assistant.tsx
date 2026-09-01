/**
 * The assistant conversation, held above the router.
 *
 * The panel is available on every screen, so the transcript has to outlive a
 * navigation: asking "which trucks are red?" and then opening one of them must
 * not throw the answer away. Keeping the turns here - in a provider mounted
 * once inside the app shell - is what makes the panel a companion to the
 * screens rather than a screen of its own.
 *
 * Two rules about scope are enforced here rather than left to the reader:
 *
 * 1. Changing customer scope clears the transcript. Every figure in it was
 *    fetched inside the previous tenant, and leaving those answers on screen
 *    under a new customer's name would be the one place in the product where a
 *    number does not mean what the scope switcher says it means.
 * 2. A reply that was already in flight when the scope changed is discarded.
 *    It was answered against the old scope, and it would otherwise land in a
 *    transcript that has just been emptied for exactly that reason.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useSendChatMessage } from "@/api/queries";
import type { Citation } from "@/api/types";
import { useScope } from "@/state/session";

export interface UserTurn {
  id: string;
  role: "user";
  text: string;
}

export interface AssistantTurn {
  id: string;
  role: "assistant";
  text: string;
  toolsUsed: string[];
  citations: Citation[];
  rounds: number;
  truncated: boolean;
  hitRoundLimit: boolean;
}

export interface FailedTurn {
  id: string;
  role: "error";
  error: unknown;
  /** Kept so the retry button can ask the same question again. */
  question: string;
}

export type Turn = UserTurn | AssistantTurn | FailedTurn;

/** How many earlier turns are replayed to the model. The API only replays the
 *  text - never previous tool results - so a longer window costs tokens
 *  without making a stale figure quotable. Four exchanges is enough for "and
 *  what about that one?" to resolve. */
const HISTORY_TURNS = 8;

interface AssistantContextValue {
  open: boolean;
  openPanel: () => void;
  closePanel: () => void;
  togglePanel: () => void;
  turns: Turn[];
  /** The question being answered right now, for the thinking indicator. */
  pendingQuestion: string | null;
  ask: (question: string) => void;
  retry: (turnId: string) => void;
  reset: () => void;
  /** Set when a scope change emptied the transcript, cleared on the next ask. */
  clearedByScopeChange: boolean;
}

const AssistantContext = createContext<AssistantContextValue | null>(null);

let nextTurnId = 1;
const makeId = () => `turn-${nextTurnId++}`;

export function AssistantProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [clearedByScopeChange, setClearedByScopeChange] = useState(false);

  const send = useSendChatMessage();
  const scope = useScope();

  // Read at mutate time so the history sent is the transcript as it stood
  // before the new question was appended.
  const turnsRef = useRef<Turn[]>(turns);
  turnsRef.current = turns;

  // Incremented whenever the transcript is emptied; a reply carrying a stale
  // generation is dropped rather than appended to a conversation it no longer
  // belongs to.
  const generation = useRef(0);

  const run = useCallback(
    (question: string) => {
      const history = turnsRef.current
        .filter((turn): turn is UserTurn | AssistantTurn => turn.role !== "error")
        .slice(-HISTORY_TURNS)
        .map((turn) => ({ role: turn.role, content: turn.text }));

      const sentAt = generation.current;
      setPendingQuestion(question);

      send.mutate(
        { message: question, history },
        {
          onSuccess: (response) => {
            if (generation.current !== sentAt) return;
            setPendingQuestion(null);
            setTurns((current) => [
              ...current,
              {
                id: makeId(),
                role: "assistant",
                text: response.reply,
                toolsUsed: response.tools_used,
                citations: response.data_cited,
                rounds: response.rounds,
                truncated: response.truncated,
                hitRoundLimit: response.hit_round_limit,
              },
            ]);
          },
          onError: (error) => {
            if (generation.current !== sentAt) return;
            setPendingQuestion(null);
            setTurns((current) => [
              ...current,
              { id: makeId(), role: "error", error, question },
            ]);
          },
        },
      );
    },
    [send],
  );

  const ask = useCallback(
    (raw: string) => {
      const question = raw.trim();
      if (!question || pendingQuestion !== null) return;
      setClearedByScopeChange(false);
      setTurns((current) => [...current, { id: makeId(), role: "user", text: question }]);
      run(question);
    },
    [pendingQuestion, run],
  );

  const retry = useCallback(
    (turnId: string) => {
      const failed = turnsRef.current.find(
        (turn): turn is FailedTurn => turn.role === "error" && turn.id === turnId,
      );
      if (!failed || pendingQuestion !== null) return;
      setTurns((current) => current.filter((turn) => turn.id !== turnId));
      run(failed.question);
    },
    [pendingQuestion, run],
  );

  const reset = useCallback(() => {
    generation.current += 1;
    setTurns([]);
    setPendingQuestion(null);
    setClearedByScopeChange(false);
  }, []);

  // Ctrl/Cmd-J from anywhere. It lives here rather than in the panel because
  // the panel is a lazy chunk that has not mounted until someone opens it, and
  // the shortcut is one of the ways they do that. Ctrl-K already belongs to
  // global search.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "j") {
        event.preventDefault();
        setOpen((current) => !current);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const previousScope = useRef(scope);
  useEffect(() => {
    if (previousScope.current === scope) return;
    previousScope.current = scope;

    const hadConversation = turnsRef.current.length > 0 || pendingQuestion !== null;
    generation.current += 1;
    setTurns([]);
    setPendingQuestion(null);
    setClearedByScopeChange(hadConversation);
  }, [scope, pendingQuestion]);

  const value = useMemo<AssistantContextValue>(
    () => ({
      open,
      openPanel: () => setOpen(true),
      closePanel: () => setOpen(false),
      togglePanel: () => setOpen((current) => !current),
      turns,
      pendingQuestion,
      ask,
      retry,
      reset,
      clearedByScopeChange,
    }),
    [open, turns, pendingQuestion, ask, retry, reset, clearedByScopeChange],
  );

  return <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>;
}

export function useAssistant(): AssistantContextValue {
  const value = useContext(AssistantContext);
  if (!value) throw new Error("useAssistant must be used inside <AssistantProvider>");
  return value;
}
