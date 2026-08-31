import { BrowserRouter } from "react-router-dom";

import { ErrorBoundary } from "@/app/ErrorBoundary";
import { Providers } from "@/app/providers";
import { AppRoutes } from "@/app/routes";

/**
 * Both v7 behaviours are opted into now rather than left to warn on every
 * page load: wrapping navigation state updates in `startTransition` is what we
 * want anyway with lazily loaded routes, and the splat path change only
 * affects relative links inside the catch-all route, which has none.
 */
const ROUTER_FUTURE = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
} as const;

export default function App() {
  return (
    <ErrorBoundary>
      <Providers>
        <BrowserRouter future={ROUTER_FUTURE}>
          <AppRoutes />
        </BrowserRouter>
      </Providers>
    </ErrorBoundary>
  );
}
