/**
 * Brief confirmations for writes: an acknowledged alert, a raised work order,
 * a deployed rule, a failed request that was rolled back.
 *
 * Optimistic updates change the row before the server answers, which is right
 * for an inbox but means a *failed* write would otherwise be invisible - the
 * row would simply snap back. The toast is what says why.
 *
 * It is announced through an `aria-live` region, since the visual change may
 * be off screen by the time it lands.
 */

import { AnimatePresence, motion } from "framer-motion";
import { AlertCircle, CheckCircle2, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { cn } from "@/lib/cn";
import { transitions } from "@/lib/motion";

type Tone = "success" | "error";

interface Toast {
  id: number;
  tone: Tone;
  title: string;
  detail?: string;
}

interface ToastContextValue {
  show: (toast: Omit<Toast, "id">) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const DISMISS_AFTER_MS = 5000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const show = useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = nextId.current++;
      setToasts((current) => [...current, { ...toast, id }]);
      window.setTimeout(() => dismiss(id), DISMISS_AFTER_MS);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-full max-w-sm flex-col gap-2"
      >
        <AnimatePresence initial={false}>
          {toasts.map((toast) => (
            <motion.div
              key={toast.id}
              layout
              initial={{ opacity: 0, y: 12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.15 } }}
              transition={transitions.base}
              className={cn(
                "pointer-events-auto flex items-start gap-2.5 rounded-xl border px-3.5 py-3 shadow-overlay",
                toast.tone === "success"
                  ? "border-hairline bg-raised"
                  : "border-risk-red/30 bg-raised",
              )}
            >
              {toast.tone === "success" ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-risk-green" aria-hidden="true" />
              ) : (
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-risk-red" aria-hidden="true" />
              )}
              <div className="min-w-0 flex-1">
                <p className="text-[0.8125rem] font-medium text-ink">{toast.title}</p>
                {toast.detail ? (
                  <p className="mt-0.5 text-[0.75rem] leading-4 text-muted">{toast.detail}</p>
                ) : null}
              </div>
              <button
                type="button"
                aria-label="Dismiss notification"
                onClick={() => dismiss(toast.id)}
                className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-faint transition-colors hover:bg-canvas hover:text-ink"
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside <ToastProvider>.");
  return value;
}
