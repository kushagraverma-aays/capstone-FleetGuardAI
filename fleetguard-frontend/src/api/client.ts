/**
 * The single door to the API.
 *
 * Every request in the product goes through `request()`. That is what makes
 * three guarantees hold without anyone having to remember them:
 *
 *  - the X-Customer-Scope header is always present and always current, so the
 *    scope switcher genuinely filters every screen;
 *  - the bearer token is attached the moment auth is turned on, with no other
 *    file changing;
 *  - errors arrive as one `ApiError` type, parsed from the backend's single
 *    error envelope, so screens branch on a slug rather than on a sentence.
 */

import { getSession, scopeHeaderValue, signOut } from "./session";

/**
 * Empty by default: the app calls "/api/..." on its own origin, which the Vite
 * dev server and the production nginx both proxy to the backend. Set
 * VITE_API_BASE_URL only when the API is on a genuinely different origin.
 */
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

/** The `problems` array a 422 carries, naming the offending field. The
 *  backend flattens pydantic's output into exactly these two strings. */
export interface ApiProblem {
  field: string;
  problem: string;
}

/**
 * One error type for the whole client.
 *
 * `slug` is the machine-readable `error` field from the envelope
 * (`not_found`, `forbidden`, `invalid_request`, ...). Branch on it. `message`
 * is a written sentence meant to be shown to a person as-is; it is not stable
 * enough to compare against.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly slug: string;
  readonly requestId: string | null;
  readonly problems: ApiProblem[];

  constructor(
    status: number,
    slug: string,
    message: string,
    requestId: string | null,
    problems: ApiProblem[] = [],
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.slug = slug;
    this.requestId = requestId;
    this.problems = problems;
  }

  /** True when retrying the same request might work: the network dropped, or
   *  the server had a bad moment. A 403 or a 404 will never come good. */
  get isRetryable(): boolean {
    return this.status === 0 || this.status >= 500 || this.status === 429;
  }
}

export type QueryValue = string | number | boolean | null | undefined;
export type QueryParams = Record<string, QueryValue | QueryValue[]>;

/** Drops empty values so `?tier=` never reaches the API, and repeats a key per
 *  item for the multi-select filters the list endpoints accept. */
export function buildQuery(params: QueryParams | undefined): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === undefined || item === null || item === "") continue;
        search.append(key, String(item));
      }
    } else {
      search.append(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  query?: QueryParams;
  body?: unknown;
  signal?: AbortSignal;
  /** Set for endpoints that answer with something other than JSON. */
  accept?: string;
}

function authHeaders(): Record<string, string> {
  const { token } = getSession();
  const headers: Record<string, string> = {
    "X-Customer-Scope": scopeHeaderValue(),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

export function apiUrl(path: string, query?: QueryParams): string {
  return `${BASE_URL}${path}${buildQuery(query)}`;
}

async function toApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("X-Request-ID");
  try {
    const payload = (await response.json()) as {
      error?: string;
      message?: string;
      request_id?: string;
      problems?: ApiProblem[];
    };
    return new ApiError(
      response.status,
      payload.error ?? "error",
      payload.message ?? response.statusText,
      payload.request_id ?? requestId,
      payload.problems ?? [],
    );
  } catch {
    // A proxy or a crash can answer with something that is not our envelope.
    return new ApiError(
      response.status,
      "error",
      response.statusText || "The server returned an unreadable response.",
      requestId,
    );
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", query, body, signal, accept = "application/json" } = options;

  const headers: Record<string, string> = { Accept: accept, ...authHeaders() };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(apiUrl(path, query), {
      method,
      headers,
      signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    // Status 0 means the request never reached the API - the backend is down,
    // or the browser blocked it. The screens phrase that differently from a
    // server error, so it needs its own slug.
    throw new ApiError(
      0,
      "network_error",
      "Could not reach the FleetGuard API. Check that the backend is running.",
      null,
    );
  }

  if (!response.ok) {
    const error = await toApiError(response);
    // An expired or rejected token must not be kept. Clearing it here rather
    // than in a screen means every route reacts at once - the guard sees no
    // token and shows the sign-in form - instead of each screen discovering
    // the dead session separately at its own next request. `/api/auth/login`
    // is excluded: a wrong password is a 401 that has nothing to do with the
    // session, and signing out in response to it would be a strange thing for
    // a login form to do.
    if (error.status === 401 && !path.startsWith("/api/auth/login")) {
      signOut();
    }
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** For the CSV export, which the browser downloads rather than parses. */
export async function requestBlob(path: string, query?: QueryParams): Promise<Blob> {
  const response = await fetch(apiUrl(path, query), {
    headers: { Accept: "text/csv", ...authHeaders() },
  });
  if (!response.ok) throw await toApiError(response);
  return response.blob();
}
