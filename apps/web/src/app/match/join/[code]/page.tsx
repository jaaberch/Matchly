"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { JerseyPicker } from "@/components/JerseyPicker";
import { useSession } from "@/components/SessionProvider";
import { Button, Card, StatusBadge } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatMatchDate } from "@/lib/format";
import type { MatchJoinPreview, Team } from "@/lib/types";

/**
 * The QR code target.
 *
 * A player scans a code taped to the fence and lands here, often signed out.
 * The match details load without an account so they can see they are in the
 * right place before being asked for a phone number.
 */
export default function JoinMatchPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = use(params);
  const router = useRouter();
  const { user, loading: sessionLoading } = useSession();

  const [preview, setPreview] = useState<MatchJoinPreview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [team, setTeam] = useState<Team>("A");
  const [jersey, setJersey] = useState<number | null>(null);
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const result = user ? await api.matches.previewAsMe(code) : await api.matches.preview(code);
      setPreview(result);
      if (result.my_team) setTeam(result.my_team);
      if (result.my_jersey_number !== null) setJersey(result.my_jersey_number);
    } catch (caught) {
      setLoadError(
        caught instanceof ApiError && caught.code === "NOT_FOUND"
          ? "That code does not match any match. Check the code on the pitch."
          : "Could not load this match. Please try again.",
      );
    }
  }, [code, user]);

  useEffect(() => {
    if (!sessionLoading) void load();
  }, [sessionLoading, load]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!preview || jersey === null) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.matches.join(preview.match_id, {
        team,
        jersey_number: jersey,
        consent,
      });
      router.push(`/match/${preview.match_id}`);
    } catch (caught) {
      setError(messageFor(caught));
      // A number may have been taken while this player was deciding.
      void load();
    } finally {
      setSubmitting(false);
    }
  }

  if (loadError) {
    return (
      <div className="animate-fade-in py-8 text-center">
        <p className="text-lg font-semibold">Match not found</p>
        <p className="mt-2 text-sm text-ink-300">{loadError}</p>
        <Link href="/" className="mt-6 inline-block text-sm text-pitch-400 underline">
          Go to your matches
        </Link>
      </div>
    );
  }

  if (!preview) {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading match">
        <div className="h-28 animate-pulse rounded-2xl bg-ink-800" />
        <div className="h-64 animate-pulse rounded-2xl bg-ink-800" />
      </div>
    );
  }

  return (
    <div className="animate-fade-in space-y-5">
      <header>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight">
              {preview.title ?? "Join this match"}
            </h1>
            <p className="mt-1 text-sm text-ink-300">
              {preview.venue_name} · {preview.field_name}
            </p>
          </div>
          <StatusBadge status={preview.status} />
        </div>
        <p className="mt-2 text-sm text-ink-200">{formatMatchDate(preview.starts_at)}</p>
      </header>

      {preview.already_joined ? (
        <Card className="p-4">
          <p className="font-semibold text-pitch-400">You are checked in</p>
          <p className="mt-1 text-sm text-ink-300">
            Team {preview.my_team} · number {preview.my_jersey_number}
          </p>
          <Button
            className="mt-4"
            fullWidth
            onClick={() => router.push(`/match/${preview.match_id}`)}
          >
            Go to the match
          </Button>
        </Card>
      ) : !preview.joinable ? (
        <Card className="p-4">
          <p className="font-semibold">Check-in is closed</p>
          <p className="mt-1 text-sm text-ink-300">
            This match has already started, so the teams are locked.
          </p>
        </Card>
      ) : !user ? (
        <Card className="p-4">
          <p className="font-semibold">Sign in to join</p>
          <p className="mt-1 text-sm text-ink-300">
            Your phone number is your account. It takes about ten seconds.
          </p>
          <Button
            className="mt-4"
            fullWidth
            size="lg"
            onClick={() => router.push(`/login?next=${encodeURIComponent(`/match/join/${code}`)}`)}
          >
            Continue with phone
          </Button>
        </Card>
      ) : (
        <form onSubmit={submit} className="space-y-5">
          <JerseyPicker
            team={team}
            onTeamChange={setTeam}
            jerseyNumber={jersey}
            onJerseyChange={setJersey}
            takenJerseys={preview.taken_jerseys}
            teamSizes={preview.team_sizes}
            disabled={submitting}
          />

          {preview.recording_disclosure && (
            <Card className="p-4">
              <h2 className="text-sm font-semibold">Recording notice</h2>
              <p className="mt-1.5 text-sm text-ink-300">{preview.recording_disclosure}</p>
              <label className="mt-3 flex items-start gap-3">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(event) => setConsent(event.target.checked)}
                  className="mt-0.5 h-5 w-5 shrink-0 rounded border-ink-500 bg-ink-700 accent-pitch-500"
                />
                <span className="text-sm text-ink-200">
                  I agree to appear in this match recording and its highlight clips.
                </span>
              </label>
            </Card>
          )}

          {error && (
            <p role="alert" className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">
              {error}
            </p>
          )}

          <Button
            type="submit"
            size="lg"
            fullWidth
            loading={submitting}
            disabled={jersey === null || !consent}
          >
            {jersey === null
              ? "Pick your number"
              : !consent
                ? "Accept the recording notice"
                : `Join team ${team} as number ${jersey}`}
          </Button>
        </form>
      )}
    </div>
  );
}

function messageFor(caught: unknown): string {
  if (!(caught instanceof ApiError)) return "Something went wrong. Please try again.";

  switch (caught.code) {
    case "JERSEY_TAKEN":
      return "Someone just took that number. Pick another one.";
    case "ALREADY_JOINED":
      return "You are already checked in to this match.";
    case "MATCH_NOT_JOINABLE":
      return "This match has started, so check-in is closed.";
    case "CONSENT_REQUIRED":
      return "You need to accept the recording notice to join.";
    default:
      return caught.message;
  }
}
