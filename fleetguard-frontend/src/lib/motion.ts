/**
 * The product's motion vocabulary, in one place.
 *
 * Spec 9: content fades and rises 8px on mount, staggered ~40ms across lists,
 * everything 200-400ms on an ease-out curve. Keeping the variants here rather
 * than inline means the whole app moves the same way, and that changing the
 * feel is one edit.
 *
 * `prefers-reduced-motion` is honoured by `useReducedMotion` at the point of
 * use: the components below swap to `still` rather than playing a shortened
 * animation, because someone who asked for less motion wants none of this,
 * not a faster version of it.
 */

import type { Transition, Variants } from "framer-motion";

export const EASE_OUT = [0.22, 1, 0.36, 1] as const;

export const transitions = {
  quick: { duration: 0.2, ease: EASE_OUT } satisfies Transition,
  base: { duration: 0.28, ease: EASE_OUT } satisfies Transition,
  slow: { duration: 0.4, ease: EASE_OUT } satisfies Transition,
};

/** The default entrance: fade in and rise 8px. */
export const riseIn: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: transitions.base },
};

/** Put on a list container; children use `riseIn`. */
export const staggerChildren: Variants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.04, delayChildren: 0.02 },
  },
};

/** For anything that should not move at all. */
export const still: Variants = {
  hidden: { opacity: 1, y: 0 },
  visible: { opacity: 1, y: 0, transition: { duration: 0 } },
};

/** Page transitions cross-fade rather than slide - a dashboard that slides on
 *  every navigation feels busy by the third click. */
export const pageTransition: Variants = {
  hidden: { opacity: 0, y: 6 },
  visible: { opacity: 1, y: 0, transition: transitions.base },
  exit: { opacity: 0, transition: transitions.quick },
};

/** The drawer that opens from the right on a row click. */
export const drawerPanel: Variants = {
  hidden: { x: "100%" },
  visible: { x: 0, transition: { duration: 0.32, ease: EASE_OUT } },
  exit: { x: "100%", transition: { duration: 0.24, ease: EASE_OUT } },
};

export const scrim: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: transitions.quick },
  exit: { opacity: 0, transition: transitions.quick },
};

/** Picks the entrance variants a component should use. */
export function entrance(reduced: boolean | null): Variants {
  return reduced ? still : riseIn;
}
