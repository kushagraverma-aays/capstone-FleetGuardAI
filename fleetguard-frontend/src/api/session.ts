/**
 * The session: which customer the UI is looking at, and the auth token if one
 * has been issued.
 *
 * This is a plain module store rather than React state on purpose. `client.ts`
 * has to read the current scope at the moment a request is built, and a value
 * that only exists inside a React context would either have to be threaded
 * through every call site or copied into the client by an effect - and an
 * effect can run after the first query has already fired, which would send the
 * previous tenant's header. Keeping one module-level value that React
 * subscribes to (see `state/session.tsx`) removes that ordering question
 * entirely.
 */

const SCOPE_KEY = "fleetguard.scope";
const TOKEN_KEY = "fleetguard.token";

/** `"all"` is the manufacturer view; a number is a single customer. The API
 *  accepts exactly these two forms in the X-Customer-Scope header. */
export type ScopeValue = "all" | number;

export interface SessionState {
  scope: ScopeValue;
  token: string | null;
}

type Listener = () => void;

const listeners = new Set<Listener>();

function readStoredScope(): ScopeValue {
  try {
    const raw = localStorage.getItem(SCOPE_KEY);
    if (raw === null || raw === "all") return "all";
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) ? parsed : "all";
  } catch {
    return "all";
  }
}

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

let state: SessionState = {
  scope: readStoredScope(),
  token: readStoredToken(),
};

function emit(next: SessionState): void {
  state = next;
  for (const listener of listeners) listener();
}

export function getSession(): SessionState {
  return state;
}

export function subscribeToSession(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setScope(scope: ScopeValue): void {
  if (state.scope === scope) return;
  try {
    localStorage.setItem(SCOPE_KEY, String(scope));
  } catch {
    /* private mode: the scope simply will not survive a reload */
  }
  emit({ ...state, scope });
}

export function setToken(token: string | null): void {
  if (state.token === token) return;
  try {
    if (token === null) localStorage.removeItem(TOKEN_KEY);
    else localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* as above */
  }
  emit({ ...state, token });
}

/** The header value the API expects for the current scope. */
export function scopeHeaderValue(scope: ScopeValue = state.scope): string {
  return scope === "all" ? "all" : String(scope);
}

/** Cache-key fragment. Every query key starts with this so one tenant's data
 *  can never be served from another tenant's cache entry. */
export function scopeKey(scope: ScopeValue = state.scope): string {
  return scope === "all" ? "all" : `customer-${scope}`;
}
