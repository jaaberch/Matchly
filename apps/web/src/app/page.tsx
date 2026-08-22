"use client";

import { RequireAuth } from "@/components/RequireAuth";
import { useSession } from "@/components/SessionProvider";
import { Card, CardHeader, EmptyState } from "@/components/ui";

/**
 * Player home.
 *
 * The three sections below are the product's home screen: upcoming matches,
 * recent matches and the latest highlights. Phase 1 ships the shell and the
 * empty states; the match and highlight endpoints arrive in Phases 2 and 4 and
 * plug straight into these sections.
 */
export default function HomePage() {
  return (
    <RequireAuth>
      <HomeContent />
    </RequireAuth>
  );
}

function HomeContent() {
  const { user } = useSession();

  return (
    <div className="animate-fade-in space-y-5">
      <div>
        <p className="text-sm text-ink-300">Welcome back</p>
        <h1 className="text-2xl font-bold tracking-tight">{user?.name}</h1>
      </div>

      <Card>
        <CardHeader title="Next match" />
        <EmptyState
          title="No upcoming match"
          description="Scan the QR code at your pitch to join a match."
        />
      </Card>

      <Card>
        <CardHeader title="Recent matches" />
        <EmptyState
          title="No matches yet"
          description="Once you play, your match appears here with its replay."
        />
      </Card>

      <Card>
        <CardHeader title="Your highlights" />
        <EmptyState
          title="No highlights yet"
          description="Your best moments are clipped automatically after each match."
        />
      </Card>
    </div>
  );
}
