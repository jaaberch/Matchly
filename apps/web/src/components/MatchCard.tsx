import Link from "next/link";

import { StatusBadge } from "@/components/ui";
import { formatMatchDate } from "@/lib/format";
import type { MatchSummary } from "@/lib/types";

/**
 * One match in a list. Status is the most-asked question in the product, so it
 * sits top-right where the eye lands after the title.
 */
export function MatchCard({ match }: { match: MatchSummary }) {
  const highlights = match.highlight_count;

  return (
    <Link
      href={`/match/${match.id}`}
      className="block rounded-2xl border border-ink-600/70 bg-ink-800 p-4 transition-colors hover:border-ink-500 active:bg-ink-700"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-semibold">{match.title ?? "Match"}</p>
          <p className="mt-0.5 truncate text-sm text-ink-300">
            {match.venue.name} · {match.field.name}
          </p>
        </div>
        <StatusBadge status={match.status} />
      </div>

      <div className="mt-3 flex items-center gap-3 text-sm text-ink-300">
        <span>{formatMatchDate(match.starts_at)}</span>
        <span aria-hidden>·</span>
        <span>
          {match.player_count} {match.player_count === 1 ? "player" : "players"}
        </span>
        {highlights > 0 && (
          <>
            <span aria-hidden>·</span>
            <span className="text-pitch-400">
              {highlights} {highlights === 1 ? "clip" : "clips"}
            </span>
          </>
        )}
      </div>
    </Link>
  );
}
