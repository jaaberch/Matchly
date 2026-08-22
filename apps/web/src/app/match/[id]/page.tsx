"use client";

import { use, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { RequireAuth } from "@/components/RequireAuth";
import { TeamRoster } from "@/components/TeamRoster";
import { Button, Card, CardHeader, EmptyState, StatusBadge } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatMatchDate } from "@/lib/format";
import type { MatchDetail, MatchStatus } from "@/lib/types";

/** Status copy written for a player waiting on their clips, not for an engineer. */
const PROGRESS: Record<MatchStatus, string | null> = {
  SCHEDULED: "Check-in is open. Scan the code at the pitch to pick your number.",
  CHECK_IN: "Check-in is open. Scan the code at the pitch to pick your number.",
  RECORDING: "The camera is rolling.",
  UPLOADING: "The recording is uploading from the pitch.",
  PROCESSING: "We are finding the best moments. This usually takes a few minutes.",
  READY: null,
  FAILED: "Something went wrong with this recording. The venue has been notified.",
};

export default function MatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <RequireAuth>
      <MatchContent matchId={id} />
    </RequireAuth>
  );
}

function MatchContent({ matchId }: { matchId: string }) {
  const router = useRouter();
  const [match, setMatch] = useState<MatchDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setMatch(await api.matches.get(matchId));
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.status === 403
          ? "You do not have access to this match."
          : "Could not load this match.",
      );
    }
  }, [matchId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll while the match is in flight. Phase 1 chose polling over websockets
  // deliberately; this is where that shows up.
  useEffect(() => {
    if (!match || !["RECORDING", "UPLOADING", "PROCESSING"].includes(match.status)) return;
    const timer = setInterval(() => void load(), 15_000);
    return () => clearInterval(timer);
  }, [match, load]);

  async function leave() {
    if (!match) return;
    setLeaving(true);
    try {
      await api.matches.leave(match.id);
      router.push("/");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not leave the match.");
      setLeaving(false);
    }
  }

  if (error) {
    return (
      <div className="py-8 text-center">
        <p className="text-lg font-semibold">Not available</p>
        <p className="mt-2 text-sm text-ink-300">{error}</p>
      </div>
    );
  }

  if (!match) {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading match">
        <div className="h-24 animate-pulse rounded-2xl bg-ink-800" />
        <div className="h-40 animate-pulse rounded-2xl bg-ink-800" />
      </div>
    );
  }

  const iAmPlaying = match.players.some((player) => player.is_me);
  const canLeave = iAmPlaying && ["SCHEDULED", "CHECK_IN"].includes(match.status);
  const progress = PROGRESS[match.status];

  return (
    <div className="animate-fade-in space-y-5">
      <header>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight">{match.title ?? "Match"}</h1>
            <p className="mt-1 text-sm text-ink-300">
              {match.venue.name} · {match.field.name}
            </p>
          </div>
          <StatusBadge status={match.status} />
        </div>
        <p className="mt-2 text-sm text-ink-200">{formatMatchDate(match.starts_at)}</p>
      </header>

      {progress && (
        <Card className="p-4">
          <p className="text-sm text-ink-200">{progress}</p>
          {match.status === "SCHEDULED" && !iAmPlaying && (
            <p className="mt-2 text-sm text-ink-400">
              Code: <span className="font-mono font-semibold text-ink-100">{match.join_code}</span>
            </p>
          )}
        </Card>
      )}

      <Card className="p-4">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-300">
          Teams
        </h2>
        {match.players.length === 0 ? (
          <p className="text-sm text-ink-400">Nobody has checked in yet.</p>
        ) : (
          <TeamRoster players={match.players} />
        )}
      </Card>

      <Card>
        <CardHeader title="Highlights" />
        {match.status === "READY" && match.highlight_count > 0 ? (
          <div className="px-4 pb-4">
            <p className="text-sm text-ink-200">
              {match.highlight_count} clips are ready from this match.
            </p>
          </div>
        ) : (
          <EmptyState
            title={match.status === "READY" ? "No clips from this match" : "Not ready yet"}
            description={
              match.status === "READY"
                ? "The pipeline did not find any standout moments."
                : "Your best moments appear here once the match has been processed."
            }
          />
        )}
      </Card>

      {canLeave && (
        <Button variant="ghost" fullWidth loading={leaving} onClick={() => void leave()}>
          Leave this match
        </Button>
      )}
    </div>
  );
}
