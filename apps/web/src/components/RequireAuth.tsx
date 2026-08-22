"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { useSession } from "./SessionProvider";

/**
 * Client-side gate for player screens.
 *
 * This is a convenience, not a security boundary — the API authorises every
 * request on its own. It exists so a signed-out player lands on the login screen
 * instead of an empty page.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Carry the destination so signing in returns the player to where they were.
    if (!loading && !user) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [loading, user, router, pathname]);

  if (loading) {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading">
        <div className="h-24 animate-pulse rounded-2xl bg-ink-800" />
        <div className="h-24 animate-pulse rounded-2xl bg-ink-800" />
      </div>
    );
  }

  if (!user) return null;

  return <>{children}</>;
}
