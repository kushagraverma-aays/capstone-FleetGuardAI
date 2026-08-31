import clsx, { type ClassValue } from "clsx";

/**
 * Class name joiner. Deliberately not `tailwind-merge`: nothing in this
 * codebase passes a competing utility down through props, and the extra
 * dependency would only hide that a component is being over-configured.
 */
export function cn(...values: ClassValue[]): string {
  return clsx(values);
}
