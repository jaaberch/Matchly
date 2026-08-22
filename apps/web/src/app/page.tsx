"use client";

import { useEffect, useState } from "react";

import { MatchCard } from "@/components/MatchCard";
import { RequireAuth } from "@/components/RequireAuth";
import { useSession } from "@/components/SessionProvider";
import { Card, CardHeader, EmptyState } from "@/components/ui";
import { api } from "@/lib/api";
import type { MatchSummary } from "@/lib/types";

export default function HomePage() {
  return (
    <RequireAuth>
      <HomeContent />
    </RequireAuth>
  );
}

function HomeContent() {
  const { user } = useSession();
  const [upcoming, setUpcoming] = useState<MatchSummary[] | null>(null);
  const [past, setPast] = useState<MatchSummary[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.matches.mine("upcoming", 5), api.matches.mine("past", 5)])
      .then(([next, history]) => {
        if (cancelled) return;
        setUpcoming(next.items);
        setPast(history.items);
      })
      .catch(() => {
        if (cancelled) return;
        setUpcoming([]);
        setPast([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="animate-fade-in space-y-5">
      <div>
        <p className="text-sm text-ink-300">Welcome back</p>
        <h1 className="text-2xl font-bold tracking-tight">{user?.name}</h1>
      </div>

      <Section
        title="Next up"
        matches={upcoming}
        emptyTitle="No upcoming match"
        emptyDescription="Scan the QR code at your pitch to join a match."
      />

      <Section
        title="Recent matches"
        matches={past}
        emptyTitle="No matches yet"
        emptyDescription="Once you play, your match appears here with its replay."
      />

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

function Section({
  title,
  matches,
  emptyTitle,
  emptyDescription,
}: {
  title: string;
  matches: MatchSummary[] | null;
  emptyTitle: string;
  emptyDescription: string;
}) {
  if (matches === null) {
    return (
      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-300">
          {title}
        </h2>
        <div className="h-24 animate-pulse rounded-2xl bg-ink-800" />
      </div>
    );
  }

  if (matches.length === 0) {
    return (
      <Card>
        <CardHeader title={title} />
        <EmptyState title={emptyTitle} description={emptyDescription} />
      </Card>
    );
  }

  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-300">{title}</h2>
      <div className="space-y-2.5">
        {matches.map((match) => (
          <MatchCard key={match.id} match={match} />
        ))}
      </div>
    </div>
  );
}
