/**
 * The right-hand detail panel.
 *
 * Spec 9 asks for a drawer rather than a page navigation on row click, and the
 * reason is worth stating: an operator working a list of red vehicles is
 * comparing rows. Navigating away loses their scroll position, their filters
 * and their place; sliding a panel over the list keeps all three.
 *
 * It is a modal dialog: focus moves in, Escape closes, and focus returns to
 * the row that opened it.
 */

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { IconButton } from "./Button";
import { cn } from "@/lib/cn";
import { drawerPanel, scrim, transitions } from "@/lib/motion";

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  /** A VIN, a customer, a status - the line under the title. */
  subtitle?: ReactNode;
  /** Actions pinned to the bottom of the panel. */
  footer?: ReactNode;
  /** A control beside the close button - "start a new conversation", and
   *  anything else that belongs to the panel rather than to its content. */
  headerAction?: ReactNode;
  children: ReactNode;
  width?: "md" | "lg" | "xl";
}

const WIDTHS = {
  md: "max-w-md",
  lg: "max-w-2xl",
  xl: "max-w-4xl",
} as const;

export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  footer,
  headerAction,
  children,
  width = "lg",
}: DrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocusTo = useRef<HTMLElement | null>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (!open) return;

    restoreFocusTo.current = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;

      // Focus stays inside the panel while it is open: tabbing out to the list
      // behind it would let someone operate a screen they cannot see.
      const focusable = panelRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    const focusTimer = window.setTimeout(() => panelRef.current?.focus(), 30);

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      window.clearTimeout(focusTimer);
      document.body.style.overflow = previousOverflow;
      restoreFocusTo.current?.focus?.();
    };
  }, [open, onClose]);

  return createPortal(
    <AnimatePresence>
      {open ? (
        <div className="fixed inset-0 z-50 flex justify-end">
          <motion.div
            variants={scrim}
            initial="hidden"
            animate="visible"
            exit="exit"
            onClick={onClose}
            className="absolute inset-0 bg-black/25 backdrop-blur-[2px]"
          />

          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            tabIndex={-1}
            variants={reduced ? scrim : drawerPanel}
            initial="hidden"
            animate="visible"
            exit="exit"
            transition={transitions.base}
            className={cn(
              "relative flex h-full w-full flex-col bg-surface shadow-overlay outline-none",
              "border-l border-hairline",
              WIDTHS[width],
            )}
          >
            <header className="flex items-start justify-between gap-4 border-b border-hairline px-6 py-4">
              <div className="min-w-0">
                <h2 className="truncate text-[1.0625rem] font-medium text-ink">{title}</h2>
                {subtitle ? (
                  <p className="mt-0.5 truncate text-[0.8125rem] text-muted">{subtitle}</p>
                ) : null}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {headerAction}
                <IconButton icon={X} label="Close panel" onClick={onClose} />
              </div>
            </header>

            <div className="scroll-thin flex-1 overflow-y-auto px-6 py-5">{children}</div>

            {footer ? (
              <footer className="flex items-center justify-end gap-2 border-t border-hairline px-6 py-3">
                {footer}
              </footer>
            ) : null}
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}
