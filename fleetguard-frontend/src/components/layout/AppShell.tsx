/**
 * The application frame: fixed sidebar, sticky top bar, routed content.
 *
 * Below the `lg` breakpoint the sidebar becomes an overlay - spec 9 asks for
 * responsive down to tablet, and a 240px column on a 900px screen leaves the
 * Fleet table unreadable. Page content cross-fades between routes rather than
 * sliding; a dashboard that slides on every click feels busy by the third one.
 *
 * The assistant hangs off the frame rather than off any screen: its provider
 * wraps the whole shell so the transcript survives navigation, and its panel
 * is the last child of the row so that on a wide screen it takes width from
 * the content instead of covering it.
 */

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { AssistantSlot } from "@/components/assistant/AssistantSlot";
import { cn } from "@/lib/cn";
import { pageTransition, still } from "@/lib/motion";
import { AssistantProvider } from "@/state/assistant";

const COLLAPSE_KEY = "fleetguard.nav-collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "true";
  } catch {
    return false;
  }
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [navOpen, setNavOpen] = useState(false);
  const location = useLocation();
  const reduced = useReducedMotion();

  const toggleCollapsed = () => {
    setCollapsed((value) => {
      const next = !value;
      try {
        localStorage.setItem(COLLAPSE_KEY, String(next));
      } catch {
        /* private mode: the choice lasts for this session */
      }
      return next;
    });
  };

  // The mobile overlay must not survive a navigation, or the next screen opens
  // behind a menu the viewer already dismissed in their head.
  useEffect(() => setNavOpen(false), [location.pathname]);

  return (
    <AssistantProvider>
      <div className="flex h-full bg-canvas">
        <div className="hidden shrink-0 lg:block">
          <Sidebar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
        </div>

        <AnimatePresence>
          {navOpen ? (
            <div className="fixed inset-0 z-40 lg:hidden">
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                onClick={() => setNavOpen(false)}
                className="absolute inset-0 bg-black/25"
              />
              <motion.div
                initial={reduced ? { opacity: 0 } : { x: "-100%" }}
                animate={reduced ? { opacity: 1 } : { x: 0 }}
                exit={reduced ? { opacity: 0 } : { x: "-100%" }}
                transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
                className="relative h-full w-60 shadow-overlay"
              >
                <Sidebar
                  collapsed={false}
                  onToggleCollapsed={() => setNavOpen(false)}
                  onNavigate={() => setNavOpen(false)}
                />
              </motion.div>
            </div>
          ) : null}
        </AnimatePresence>

        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar onOpenNav={() => setNavOpen(true)} />

          <main className="scroll-thin flex-1 overflow-y-auto">
            <AnimatePresence mode="wait">
              <motion.div
                key={location.pathname}
                variants={reduced ? still : pageTransition}
                initial="hidden"
                animate="visible"
                exit="exit"
                className={cn("mx-auto w-full max-w-[92rem] px-4 py-6 sm:px-6 lg:px-8")}
              >
                <Outlet />
              </motion.div>
            </AnimatePresence>
          </main>
        </div>

        <AssistantSlot />
      </div>
    </AssistantProvider>
  );
}
