/**
 * Client-side session storage.
 *
 * Tokens live in `localStorage`: this is a mobile web app that players open from
 * a WhatsApp link, and a session that survives closing the tab is the difference
 * between watching your highlights and giving up. The access token is short-lived
 * and the refresh token rotates on every use, which is what limits the exposure.
 *
 * Every read is guarded for server-side rendering and for browsers that block
 * storage entirely.
 */

import type { TokenPair, User } from "./types";

const STORAGE_KEY = "matchly.session";

export interface Session {
  access_token: string;
  refresh_token: string;
  user: User;
}

export function getTokens(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function storeTokens(tokens: TokenPair): Session {
  const session: Session = {
    access_token: tokens.access_token,
    refresh_token: tokens.refresh_token,
    user: tokens.user,
  };
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    // A private window with storage disabled still works for this tab.
  }
  notify();
  return session;
}

export function updateStoredUser(user: User): void {
  const session = getTokens();
  if (!session) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...session, user }));
  } catch {
    /* ignore */
  }
  notify();
}

export function clearTokens(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  notify();
}

// ── change notification ────────────────────────────────────────────────────
const listeners = new Set<() => void>();

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notify(): void {
  listeners.forEach((listener) => listener());
}
