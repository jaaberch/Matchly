"use client";

import { useState } from "react";

import { formatClock, formatScore } from "@/lib/format";
import type { Highlight } from "@/lib/types";

const TYPE_LABEL: Record<string, string> = {
  GOAL_AREA_ACTION: "Near the goal",
  HIGH_INTENSITY: "End to end",
  CELEBRATION: "Celebration",
  TEAM_BUILDUP: "Build-up",
  GENERIC: "Moment",
};

/**
 * The clips from a match.
 *
 * One plays at a time: these are watched on a phone, often on mobile data, so
 * nothing loads until it is tapped (`preload="none"`) and starting one stops
 * the other.
 */
export function HighlightList({ highlights }: { highlights: Highlight[] }) {
  const [playing, setPlaying] = useState<string | null>(null);

  return (
    <ul className="space-y-2.5">
      {highlights.map((highlight) => (
        <li key={highlight.id}>
          {playing === highlight.id && highlight.video_url ? (
            <video
              src={highlight.video_url}
              poster={highlight.thumbnail_url ?? undefined}
              controls
              autoPlay
              playsInline
              onEnded={() => setPlaying(null)}
              className="w-full rounded-xl bg-black"
            />
          ) : (
            <button
              type="button"
              onClick={() => setPlaying(highlight.id)}
              disabled={!highlight.video_url}
              className="flex w-full items-center gap-3 rounded-xl border border-ink-600/70 bg-ink-800 p-2.5 text-left transition-colors hover:border-ink-500 disabled:opacity-50"
            >
              <span className="relative grid h-14 w-24 shrink-0 place-items-center overflow-hidden rounded-lg bg-ink-700">
                {highlight.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={highlight.thumbnail_url}
                    alt=""
                    className="h-full w-full object-cover"
                  />
                ) : null}
                <span className="absolute grid h-8 w-8 place-items-center rounded-full bg-ink-900/70 text-sm text-white">
                  ▶
                </span>
              </span>

              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {TYPE_LABEL[highlight.type] ?? "Moment"}
                  {highlight.player && (
                    <span className="ml-1.5 text-ink-300">
                      #{highlight.player.jersey_number} {highlight.player.name}
                    </span>
                  )}
                </span>
                <span className="mt-0.5 block text-xs text-ink-400">
                  {formatClock(highlight.start_time)} · {Math.round(highlight.duration)}s ·{" "}
                  <span className="text-pitch-400">{formatScore(highlight.score)}</span>
                </span>
              </span>
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
