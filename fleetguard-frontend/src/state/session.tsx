/**
 * React's view of the session store in `api/session.ts`.
 *
 * `useSyncExternalStore` rather than a context value with `useState` because
 * the API client reads the same store synchronously when it builds a request.
 * One value, two readers, no chance of the header and the cache key
 * disagreeing about which customer is on screen.
 */

import { useCallback, useSyncExternalStore } from "react";

import {
  getSession,
  scopeKey,
  setScope,
  setToken,
  signIn,
  signOut,
  subscribeToSession,
  type Identity,
  type ScopeValue,
} from "@/api/session";

export function useSession() {
  const state = useSyncExternalStore(subscribeToSession, getSession, getSession);

  const changeScope = useCallback((scope: ScopeValue) => setScope(scope), []);
  const changeToken = useCallback((token: string | null) => setToken(token), []);

  return {
    scope: state.scope,
    token: state.token,
    identity: state.identity,
    /** True once someone has signed in. The router shows the app on this and
     *  the login screen otherwise; the server still decides what the token can
     *  actually reach. */
    isSignedIn: state.token !== null,
    /** Cache-key fragment for the current scope. */
    scopeKey: scopeKey(state.scope),
    setScope: changeScope,
    setToken: changeToken,
    signIn: useCallback(
      (token: string, identity: Identity) => signIn(token, identity),
      [],
    ),
    signOut: useCallback(() => signOut(), []),
  };
}

/** Just the scope, for the many call sites that only need the cache key. */
export function useScope(): ScopeValue {
  return useSyncExternalStore(subscribeToSession, getSession, getSession).scope;
}
