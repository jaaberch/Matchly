"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";
import { clearTokens, getTokens, storeTokens, subscribe, updateStoredUser } from "@/lib/auth";
import type { TokenPair, User } from "@/lib/types";

interface SessionValue {
  user: User | null;
  /** True until the stored session has been read; screens must not flash while loading. */
  loading: boolean;
  signIn: (tokens: TokenPair) => void;
  signOut: () => Promise<void>;
  setUser: (user: User) => void;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    // localStorage is unavailable during SSR, so the session is read on mount.
    const session = getTokens();
    setUserState(session?.user ?? null);
    setLoading(false);

    return subscribe(() => {
      setUserState(getTokens()?.user ?? null);
    });
  }, []);

  useEffect(() => {
    // Re-validate against the API so a revoked or deleted account is not shown a
    // stale profile from localStorage.
    if (!user) return;
    let cancelled = false;
    api.users
      .me()
      .then((fresh) => {
        if (!cancelled) updateStoredUser(fresh);
      })
      .catch(() => {
        if (!cancelled) clearTokens();
      });
    return () => {
      cancelled = true;
    };
    // Runs once per sign-in, not on every user object change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  const signIn = useCallback((tokens: TokenPair) => {
    storeTokens(tokens);
    setUserState(tokens.user);
  }, []);

  const signOut = useCallback(async () => {
    const session = getTokens();
    if (session?.refresh_token) {
      // Best effort: the local session is cleared even if the call fails.
      await api.auth.logout(session.refresh_token).catch(() => undefined);
    }
    clearTokens();
    setUserState(null);
    router.push("/login");
  }, [router]);

  const setUser = useCallback((next: User) => {
    updateStoredUser(next);
    setUserState(next);
  }, []);

  const value = useMemo(
    () => ({ user, loading, signIn, signOut, setUser }),
    [user, loading, signIn, signOut, setUser],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside <SessionProvider>");
  return context;
}
