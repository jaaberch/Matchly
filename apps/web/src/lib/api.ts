/**
 * Typed API client.
 *
 * Responsibilities, and deliberately nothing else:
 *  - attach the access token
 *  - refresh once on a 401 and replay the original request
 *  - turn the API's error envelope into a typed `ApiError` the UI can switch on
 */

import type {
  ApiErrorBody,
  MatchDetail,
  MatchJoinPreview,
  MatchPlayer,
  MatchHighlights,
  MatchSummary,
  Page,
  RequestOtpResult,
  Team,
  TokenPair,
  User,
  VideoDetail,
} from "./types";
import { clearTokens, getTokens, storeTokens } from "./auth";

const BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId?: string;

  constructor(status: number, body: ApiErrorBody["error"]) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details ?? {};
    this.requestId = body.request_id;
  }

  /** True for errors the user can fix by trying again with different input. */
  get isRecoverable(): boolean {
    return this.status < 500;
  }
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  auth?: boolean;
  /** Internal: prevents an infinite refresh loop. */
  _retried?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, auth = true, _retried = false, headers, ...rest } = options;

  const finalHeaders = new Headers(headers);
  if (body !== undefined) finalHeaders.set("Content-Type", "application/json");
  if (auth) {
    const tokens = getTokens();
    if (tokens?.access_token) {
      finalHeaders.set("Authorization", `Bearer ${tokens.access_token}`);
    }
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    ...rest,
    headers: finalHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  // The access token is short-lived; refresh once, then replay.
  if (response.status === 401 && auth && !_retried) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return request<T>(path, { ...options, _retried: true });
    }
    clearTokens();
  }

  if (response.status === 204) return undefined as T;

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    const envelope = (payload as ApiErrorBody | null)?.error;
    throw new ApiError(
      response.status,
      envelope ?? { code: "NETWORK_ERROR", message: "Could not reach Matchly." },
    );
  }

  return payload as T;
}

let refreshInFlight: Promise<boolean> | null = null;

/** Refreshes at most once concurrently, so parallel 401s cause one round trip. */
async function tryRefresh(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;

  const tokens = getTokens();
  if (!tokens?.refresh_token) return false;

  refreshInFlight = (async () => {
    try {
      const refreshed = await request<TokenPair>("/api/v1/auth/refresh", {
        method: "POST",
        auth: false,
        body: { refresh_token: tokens.refresh_token },
      });
      storeTokens(refreshed);
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

export const api = {
  auth: {
    requestOtp: (phone: string) =>
      request<RequestOtpResult>("/api/v1/auth/request-otp", {
        method: "POST",
        auth: false,
        body: { phone },
      }),

    verifyOtp: (phone: string, code: string, name?: string) =>
      request<TokenPair>("/api/v1/auth/verify-otp", {
        method: "POST",
        auth: false,
        body: { phone, code, name: name || undefined },
      }),

    logout: (refreshToken: string) =>
      request<void>("/api/v1/auth/logout", {
        method: "POST",
        body: { refresh_token: refreshToken },
      }),
  },

  matches: {
    /** Public: the QR code target, readable before the player has an account. */
    preview: (joinCode: string) =>
      request<MatchJoinPreview>(
        `/api/v1/matches/join/${encodeURIComponent(joinCode)}`,
        { auth: false },
      ),

    /** Same endpoint, but signed in — the response then says whether you joined. */
    previewAsMe: (joinCode: string) =>
      request<MatchJoinPreview>(`/api/v1/matches/join/${encodeURIComponent(joinCode)}`),

    get: (matchId: string) => request<MatchDetail>(`/api/v1/matches/${matchId}`),

    join: (matchId: string, body: { team: Team; jersey_number: number; consent: boolean }) =>
      request<MatchPlayer>(`/api/v1/matches/${matchId}/join`, {
        method: "POST",
        body,
      }),

    leave: (matchId: string) =>
      request<void>(`/api/v1/matches/${matchId}/players/me`, { method: "DELETE" }),

    highlights: (matchId: string, options: { mine?: boolean } = {}) =>
      request<MatchHighlights>(
        `/api/v1/matches/${matchId}/highlights${options.mine ? "?mine=true" : ""}`,
      ),

    video: (matchId: string) => request<VideoDetail>(`/api/v1/matches/${matchId}/video`),

    mine: (scope: "all" | "upcoming" | "past" = "all", pageSize = 20) =>
      request<Page<MatchSummary>>(
        `/api/v1/users/me/matches?scope=${scope}&page_size=${pageSize}`,
      ),
  },

  users: {
    me: () => request<User>("/api/v1/users/me"),

    updateMe: (changes: { name?: string; avatar?: string }) =>
      request<User>("/api/v1/users/me", { method: "PATCH", body: changes }),

    deleteMe: () => request<void>("/api/v1/users/me", { method: "DELETE" }),
  },
};

export type { Page };
