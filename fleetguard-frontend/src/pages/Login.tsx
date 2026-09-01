/**
 * The front door.
 *
 * Three seeded roles, offered as cards, plus a plain email and password form.
 * The cards come from `GET /api/auth/demo-accounts`, which the backend serves
 * only while `AUTH_ENABLED` is false - nothing here hardcodes a credential, so
 * with enforcement on the cards simply do not appear and the form is the only
 * way in.
 *
 * Signing in is real either way: it posts to `/api/auth/login`, gets a real
 * token signed against a real bcrypt hash, and every request afterwards
 * carries it. What `AUTH_ENABLED` changes is whether the API *requires* the
 * token, not whether the token means anything - so choosing the read-only
 * viewer here genuinely removes write actions from the product.
 */

import { motion } from "framer-motion";
import { AlertCircle, ArrowRight, Building2, Eye, Gauge, ShieldCheck } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useDemoAccounts, useLogin } from "@/api/queries";
import type { DemoAccount } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { TextInput } from "@/components/ui/Input";
import { cn } from "@/lib/cn";
import { riseIn, staggerChildren, transitions } from "@/lib/motion";
import { useSession } from "@/state/session";

/** One icon per role, so the three cards are distinguishable at a glance
 *  rather than by reading three paragraphs. */
const ROLE_ICONS: Record<string, typeof Gauge> = {
  manufacturer_admin: ShieldCheck,
  customer_admin: Building2,
  viewer: Eye,
};

interface LocationState {
  /** Where the guard bounced us from, so signing in resumes that page. */
  from?: string;
}

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isSignedIn } = useSession();

  const demo = useDemoAccounts();
  const login = useLogin();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState<string | null>(null);

  const from = (location.state as LocationState | null)?.from ?? "/";

  // Someone who is already signed in has no business on this screen - they
  // arrived by typing the URL or by using the back button after signing in.
  useEffect(() => {
    if (isSignedIn) navigate(from, { replace: true });
  }, [isSignedIn, from, navigate]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!email.trim() || !password) return;
    setPending(null);
    login.mutate({ email: email.trim(), password });
  }

  function signInAs(account: DemoAccount) {
    setEmail(account.email);
    setPassword(account.password);
    setPending(account.email);
    login.mutate({ email: account.email, password: account.password });
  }

  const accounts = demo.data?.accounts ?? [];

  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <motion.main
        initial="hidden"
        animate="visible"
        variants={staggerChildren}
        className="mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center gap-10 px-6 py-12"
      >
        <motion.header variants={riseIn} className="text-center">
          <span className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-accent">
            <Gauge className="h-5 w-5 text-white" aria-hidden="true" />
          </span>
          <h1 className="text-[1.375rem] font-semibold tracking-tight text-ink">
            FleetGuard <span className="text-accent">AI</span>
          </h1>
          <p className="mx-auto mt-2 max-w-md text-sm leading-5 text-muted">
            Predictive maintenance for commercial fleets. Sign in to see which
            components are about to fail, when, and what it will cost.
          </p>
        </motion.header>

        {accounts.length > 0 ? (
          <motion.section variants={riseIn} aria-labelledby="roles-heading">
            <h2
              id="roles-heading"
              className="mb-3 text-center text-[0.75rem] font-medium uppercase tracking-wide text-faint"
            >
              Choose a role
            </h2>
            <ul className="grid gap-3 sm:grid-cols-3">
              {accounts.map((account) => {
                const Icon = ROLE_ICONS[account.role] ?? ShieldCheck;
                const busy = login.isPending && pending === account.email;
                return (
                  <li key={account.email}>
                    <button
                      type="button"
                      onClick={() => signInAs(account)}
                      disabled={login.isPending}
                      className={cn(
                        "group flex h-full w-full flex-col gap-2 rounded-xl border border-hairline",
                        "bg-surface p-4 text-left transition-colors duration-150 ease-out-soft",
                        "hover:border-accent/50 hover:bg-canvas",
                        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                        "disabled:cursor-not-allowed disabled:opacity-60",
                      )}
                    >
                      <span className="flex items-center gap-2">
                        <Icon className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
                        <span className="text-sm font-medium text-ink">
                          {account.role_label}
                        </span>
                      </span>
                      <span className="text-[0.75rem] leading-4 text-muted">
                        {account.description}
                      </span>
                      <span className="mt-auto flex items-center gap-1.5 pt-2 text-[0.75rem] text-faint">
                        <span className="truncate">
                          {account.customer_name ?? "All customers"}
                        </span>
                        <ArrowRight
                          className={cn(
                            "ml-auto h-3.5 w-3.5 shrink-0 transition-transform duration-150",
                            "group-hover:translate-x-0.5",
                            busy && "animate-pulse",
                          )}
                          aria-hidden="true"
                        />
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </motion.section>
        ) : null}

        <motion.section
          variants={riseIn}
          aria-labelledby="signin-heading"
          className="mx-auto w-full max-w-sm"
        >
          {accounts.length > 0 ? (
            <div className="mb-5 flex items-center gap-3" aria-hidden="true">
              <span className="h-px flex-1 bg-hairline" />
              <span className="text-[0.75rem] text-faint">or sign in</span>
              <span className="h-px flex-1 bg-hairline" />
            </div>
          ) : null}

          <h2 id="signin-heading" className="sr-only">
            Sign in with an email address
          </h2>

          <form onSubmit={submit} className="space-y-3">
            <div className="space-y-1.5">
              <label htmlFor="email" className="block text-[0.8125rem] text-muted">
                Email
              </label>
              <TextInput
                id="email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@fleetguard.ai"
                required
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="password" className="block text-[0.8125rem] text-muted">
                Password
              </label>
              <TextInput
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>

            {login.isError ? (
              <motion.p
                role="alert"
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={transitions.quick}
                className="flex items-start gap-2 rounded-lg bg-risk-red-soft px-3 py-2 text-[0.8125rem] leading-5 text-risk-red"
              >
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                {login.error.message}
              </motion.p>
            ) : null}

            <Button
              type="submit"
              variant="primary"
              loading={login.isPending}
              disabled={!email.trim() || !password}
              className="w-full"
            >
              Sign in
            </Button>
          </form>

          {demo.data ? (
            <p className="mt-4 text-center text-[0.75rem] leading-4 text-faint">
              {demo.data.note}
            </p>
          ) : null}
        </motion.section>
      </motion.main>
    </div>
  );
}
