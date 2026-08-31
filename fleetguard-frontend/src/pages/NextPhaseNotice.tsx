/**
 * TRANSITIONAL - delete this file in phase 7.
 *
 * The build is phased: this phase delivers the foundation (theme, primitives,
 * layout, routing, API client, query layer) and phase 7 builds the seven
 * screens on top of it. Every route therefore exists and is navigable today,
 * and says what it will hold, rather than 404ing or showing invented numbers.
 *
 * Each notice lists the screen's real contents from the specification, so this
 * doubles as the checklist phase 7 works through.
 */

import { Hammer } from "lucide-react";

import { Card } from "@/components/ui/Card";

interface NextPhaseNoticeProps {
  screen: string;
  /** What this screen will contain, in the order it will appear. */
  contents: string[];
  /** Which endpoints already answer for it - the data is there, the screen is not. */
  endpoints: string[];
}

export function NextPhaseNotice({ screen, contents, endpoints }: NextPhaseNoticeProps) {
  return (
    <Card className="p-6">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft">
          <Hammer className="h-4 w-4 text-accent" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h2 className="text-[0.9375rem] font-medium text-ink">
            {screen} is built in the next phase
          </h2>
          <p className="mt-1 max-w-2xl text-[0.8125rem] leading-5 text-muted">
            The foundation this screen sits on - the API client, the query layer, the theme,
            the shared table, drawer, chart and skeleton components - is in place and working.
            The screen itself lands next.
          </p>

          <div className="mt-5 grid gap-6 sm:grid-cols-2">
            <div>
              <p className="text-label font-medium uppercase tracking-wider text-faint">
                What it will show
              </p>
              <ul className="mt-2 space-y-1.5 text-[0.8125rem] leading-5 text-muted">
                {contents.map((item) => (
                  <li key={item} className="flex gap-2">
                    <span className="mt-[0.45rem] h-1 w-1 shrink-0 rounded-full bg-faint" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <p className="text-label font-medium uppercase tracking-wider text-faint">
                Endpoints already serving it
              </p>
              <ul className="mt-2 space-y-1.5 font-mono text-[0.75rem] leading-5 text-muted">
                {endpoints.map((endpoint) => (
                  <li key={endpoint}>{endpoint}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}
