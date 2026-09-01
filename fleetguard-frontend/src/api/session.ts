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
const IDENTITY_KEY = "fleetguard.identity";

/** `"all"` is the manufacturer view; a number is a single customer. The API
 *  accepts exactly these two forms in the X-Customer-Scope header. */
export type ScopeValue = "all" | number;

/**
 * Who signed in, kept beside the token.
 *
 * `/api/auth/me` is the authority on this and the UI reads it from there, but
 * that is a request, and the router has to decide whether to show the app or
 * the login screen before any request has come back. Persisting the identity
 * that came with the token removes a full-screen flash of the sign-in form on
 * every reload; anything the server disagrees with is corrected the moment
 * `me` answers.
 */
export interface Identity {
  email: string;
  fullName: string;
  role: string;
  customerId: number | null;
}

export interface SessionState {
  scope: ScopeValue;
  token: string | null;
  identity: Identity | null;
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

function readStoredIdentity(): Identity | null {
  try {
    const raw = localStorage.getItem(IDENTITY_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Identity>;
    if (typeof parsed.email !== "string" || typeof parsed.role !== "string") return null;
    return {
      email: parsed.email,
      fullName: typeof parsed.fullName === "string" ? parsed.fullName : parsed.email,
      role: parsed.role,
      customerId: typeof parsed.customerId === "number" ? parsed.customerId : null,
    };
  } catch {
    // Unreadable or hand-edited: treat it as signed out rather than trusting it.
    return null;
  }
}

let state: SessionState = {
  scope: readStoredScope(),
  token: readStoredToken(),
  identity: readStoredIdentity(),
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

/**
 * Record a completed sign-in: the token, who it belongs to, and the scope that
 * identity implies.
 *
 * All three move together deliberately. A token stored without its scope would
 * leave the previous user's `X-Customer-Scope` header on the very first
 * request after signing in, and a manufacturer signing in after a customer
 * would spend one render looking at the wrong tenant.
 */
export function signIn(token: string, identity: Identity): void {
  const scope: ScopeValue = identity.customerId ?? "all";
  try {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(IDENTITY_KEY, JSON.stringify(identity));
    localStorage.setItem(SCOPE_KEY, String(scope));
  } catch {
    /* private mode: the session simply will not survive a reload */
  }
  emit({ scope, token, identity });
}

/** Sign out. The scope goes back to the manufacturer default so the next
 *  person to sign in never inherits the last one's tenant. */
export function signOut(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(IDENTITY_KEY);
    localStorage.removeItem(SCOPE_KEY);
  } catch {
    /* as above */
  }
  emit({ scope: "all", token: null, identity: null });
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
