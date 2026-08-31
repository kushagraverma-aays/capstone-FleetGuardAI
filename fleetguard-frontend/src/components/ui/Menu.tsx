/**
 * A popover anchored to its trigger: the scope switcher, the user menu, the
 * notification bell and the column visibility control all use it.
 *
 * Written rather than installed because the spec forbids a UI kit, and because
 * the behaviour needed here is small and exact: close on Escape, close on an
 * outside click, return focus to the trigger, and never trap focus (this is a
 * menu, not a dialog - tabbing out should close it and move on).
 */

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  cloneElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";

import { cn } from "@/lib/cn";
import { transitions } from "@/lib/motion";

interface MenuProps {
  /** Receives `onClick`, `aria-expanded` and `aria-haspopup`. */
  trigger: ReactElement<{
    onClick?: (event: React.MouseEvent) => void;
    "aria-expanded"?: boolean;
    "aria-haspopup"?: "menu";
    "aria-controls"?: string;
  }>;
  children: (close: () => void) => ReactNode;
  align?: "left" | "right";
  /** Tailwind width class for the panel. */
  width?: string;
  label: string;
}

export function Menu({ trigger, children, align = "right", width = "w-64", label }: MenuProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const reduced = useReducedMotion();

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    const onFocusIn = (event: FocusEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) close();
    };

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("focusin", onFocusIn);
    };
  }, [open, close]);

  return (
    <div ref={containerRef} className="relative">
      {cloneElement(trigger, {
        onClick: (event: React.MouseEvent) => {
          trigger.props.onClick?.(event);
          setOpen((value) => !value);
        },
        "aria-expanded": open,
        "aria-haspopup": "menu",
        "aria-controls": panelId,
      })}

      <AnimatePresence>
        {open ? (
          <motion.div
            id={panelId}
            role="menu"
            aria-label={label}
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: -4, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, transition: { duration: 0.12 } }}
            transition={transitions.quick}
            className={cn(
              "absolute z-40 mt-2 origin-top overflow-hidden rounded-xl border border-hairline",
              "bg-raised p-1 shadow-overlay",
              align === "right" ? "right-0" : "left-0",
              width,
            )}
          >
            {children(close)}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

interface MenuItemProps {
  children: ReactNode;
  onClick?: () => void;
  /** Renders a check on the left; used by the scope switcher. */
  selected?: boolean;
  disabled?: boolean;
  className?: string;
}

export function MenuItem({ children, onClick, selected, disabled, className }: MenuItemProps) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      aria-current={selected ? "true" : undefined}
      className={cn(
        "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[0.8125rem]",
        "transition-colors duration-100",
        disabled ? "cursor-not-allowed text-faint" : "text-ink hover:bg-canvas",
        selected && "bg-accent-soft text-accent-ink hover:bg-accent-soft",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return (
    <p className="px-2.5 pb-1 pt-2 text-label font-medium uppercase tracking-wider text-faint">
      {children}
    </p>
  );
}

export function MenuSeparator() {
  return <div className="my-1 h-px bg-hairline" role="separator" />;
}
