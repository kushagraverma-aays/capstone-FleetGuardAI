/**
 * Everything the tree needs above the router.
 *
 * The query defaults are the important part. A 404 or a 403 is a settled
 * answer - retrying it three times only delays the message the viewer needs to
 * read - so retries are limited to errors that could plausibly come good.
 * Window-focus refetching is off: this data is recomputed by a scoring job,
 * not by the second, and a dashboard that reloads every time someone alt-tabs
 * back to it looks unstable.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError } from "@/api/client";
import { ThemeProvider } from "@/state/theme";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && !error.isRetryable) return false;
          return failureCount < 2;
        },
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 4000),
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export function Providers({ children }: { children: ReactNode }) {
  // Created once per app instance rather than at module scope, so a test can
  // mount a second app without sharing a cache with the first.
  const [queryClient] = useState(createQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>{children}</ThemeProvider>
    </QueryClientProvider>
  );
}
