/**
 * A centred confirmation for the few actions that change what the fleet is
 * scored against.
 *
 * Deploying a rule re-scores every vehicle for that component the next time
 * scoring runs, which moves probabilities, tiers, remaining life and every
 * currency figure on every screen. That deserves a sentence saying so and a
 * deliberate second click - not a toast after the fact.
 */

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { Button } from "./Button";
import { transitions } from "@/lib/motion";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** What will happen, in plain words. */
  description: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
  /** Extra detail - a formula, a diff, the metrics being accepted. */
  children?: ReactNode;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  onConfirm,
  onCancel,
  loading = false,
  children,
}: ConfirmDialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKeyDown);
    const timer = window.setTimeout(() => panelRef.current?.focus(), 20);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      window.clearTimeout(timer);
    };
  }, [open, onCancel]);

  return createPortal(
    <AnimatePresence>
      {open ? (
        <div className="fixed inset-0 z-[55] flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={transitions.quick}
            onClick={onCancel}
            className="absolute inset-0 bg-black/30 backdrop-blur-[2px]"
          />
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            tabIndex={-1}
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.99 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, transition: { duration: 0.12 } }}
            transition={transitions.base}
            className="relative w-full max-w-lg rounded-panel border border-hairline bg-raised p-5 shadow-overlay outline-none"
          >
            <h2 className="text-[1rem] font-medium text-ink">{title}</h2>
            <div className="mt-1.5 text-[0.8125rem] leading-5 text-muted">{description}</div>
            {children ? <div className="mt-4">{children}</div> : null}
            <div className="mt-5 flex justify-end gap-2">
              <Button onClick={onCancel} disabled={loading}>
                Cancel
              </Button>
              <Button variant="primary" onClick={onConfirm} loading={loading}>
                {confirmLabel}
              </Button>
            </div>
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}
