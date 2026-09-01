/**
 * The last line of defence.
 *
 * A render error in one screen must not leave the operator looking at a white
 * page with no way back. This catches it, shows what happened, and offers the
 * two things that actually help: reload, or go back to the Command Centre.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Deliberately console.error and nothing else: there is no error-reporting
    // service in this deployment, and swallowing it silently would make a
    // reproducible bug invisible.
    console.error("Unhandled render error", error, info.componentStack);
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="flex h-full items-center justify-center bg-canvas p-6">
        <EmptyState
          title="This screen stopped unexpectedly"
          description={
            <>
              {error.message || "A rendering error interrupted the page."} Reloading usually
              clears it; if it happens again, the browser console has the details.
            </>
          }
          action={
            <div className="flex gap-2">
              <Button variant="primary" onClick={() => window.location.reload()}>
                Reload
              </Button>
              <Button onClick={() => window.location.assign("/")}>Command Centre</Button>
            </div>
          }
        />
      </div>
    );
  }
}
