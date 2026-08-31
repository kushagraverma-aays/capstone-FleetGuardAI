/**
 * Where the assistant panel is mounted, and when.
 *
 * The panel carries the Markdown renderer, which is the single largest
 * dependency in the product and is of no use to a page load that never opens
 * the assistant. So it is a lazy chunk: nothing is fetched during the first
 * paint, the browser pulls it in once it is idle, and the panel itself is only
 * mounted after the first time it is opened.
 *
 * The keyboard shortcut lives in the provider rather than here, precisely so
 * that Ctrl-J works on a page where this component has not mounted anything
 * yet.
 */

import { Suspense, lazy, useEffect, useState } from "react";

import { useAssistant } from "@/state/assistant";

const AssistantPanel = lazy(() =>
  import("./AssistantPanel").then((module) => ({ default: module.AssistantPanel })),
);

/** Fetches the chunk once the browser has nothing better to do, so the first
 *  click opens an already-loaded panel. */
function usePrefetchOnIdle() {
  useEffect(() => {
    const load = () => {
      void import("./AssistantPanel");
    };
    if (typeof window.requestIdleCallback === "function") {
      const handle = window.requestIdleCallback(load, { timeout: 4000 });
      return () => window.cancelIdleCallback(handle);
    }
    const timer = window.setTimeout(load, 2000);
    return () => window.clearTimeout(timer);
  }, []);
}

export function AssistantSlot() {
  const { open } = useAssistant();
  const [everOpened, setEverOpened] = useState(open);

  usePrefetchOnIdle();

  useEffect(() => {
    if (open) setEverOpened(true);
  }, [open]);

  if (!everOpened) return null;

  return (
    <Suspense fallback={null}>
      <AssistantPanel />
    </Suspense>
  );
}
