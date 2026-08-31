/**
 * A media query as React state.
 *
 * Tailwind handles every responsive question in this product by class, except
 * one: the assistant panel docks beside the content on a wide screen and
 * covers it on a narrow one, and those are two different component trees
 * rather than two sets of classes - a docked panel is laid out in flow, an
 * overlay is a modal dialog with a focus trap. That decision has to be made in
 * JavaScript, so the breakpoint is read here.
 *
 * The value is subscribed rather than sampled, so dragging a window across the
 * breakpoint switches modes rather than leaving the panel in the wrong one.
 */

import { useSyncExternalStore } from "react";

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const media = window.matchMedia(query);
      media.addEventListener("change", onChange);
      return () => media.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    // Server-rendered HTML has no viewport; the narrow case is the safe guess.
    () => false,
  );
}

/** The `xl` breakpoint, where there is room for the assistant to sit beside a
 *  screen instead of on top of it. */
export const WIDE_SCREEN = "(min-width: 1280px)";
