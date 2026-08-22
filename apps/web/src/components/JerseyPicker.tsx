"use client";

import { JerseyNumber } from "./TeamRoster";
import type { Team } from "@/lib/types";

/**
 * Team and number selection for check-in.
 *
 * Taken numbers are shown as taken rather than hidden: a player looking for
 * their usual shirt should see that someone else has it, not wonder where it
 * went. Selection happens at a pitch, on a phone, often in the dark — so the
 * targets are large and the state is obvious.
 */
export function JerseyPicker({
  team,
  onTeamChange,
  jerseyNumber,
  onJerseyChange,
  takenJerseys,
  teamSizes,
  disabled = false,
}: {
  team: Team;
  onTeamChange: (team: Team) => void;
  jerseyNumber: number | null;
  onJerseyChange: (jersey: number) => void;
  takenJerseys: Record<Team, number[]>;
  teamSizes: Record<Team, number>;
  disabled?: boolean;
}) {
  const taken = new Set(takenJerseys[team] ?? []);

  return (
    <div className="space-y-5">
      <div>
        <p className="field-label mb-2">Your team</p>
        <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Team">
          {(["A", "B"] as const).map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={team === option}
              disabled={disabled}
              onClick={() => onTeamChange(option)}
              className={`h-14 rounded-xl border text-base font-semibold transition-colors disabled:opacity-50 ${
                team === option
                  ? "border-pitch-500 bg-pitch-500/15 text-pitch-300"
                  : "border-ink-600 bg-ink-800 text-ink-200 hover:border-ink-500"
              }`}
            >
              Team {option}
              <span className="ml-1.5 text-sm font-normal text-ink-400">
                ({teamSizes[option] ?? 0})
              </span>
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="field-label mb-2">
          Your shirt number
          {jerseyNumber !== null && (
            <span className="ml-2 font-normal text-ink-400">selected: {jerseyNumber}</span>
          )}
        </p>
        <div className="grid grid-cols-6 gap-1.5" role="radiogroup" aria-label="Shirt number">
          {Array.from({ length: 40 }, (_, index) => index + 1).map((number) => {
            const isTaken = taken.has(number);
            const isSelected = jerseyNumber === number;
            return (
              <button
                key={number}
                type="button"
                role="radio"
                aria-checked={isSelected}
                aria-label={`Number ${number}${isTaken ? " (taken)" : ""}`}
                disabled={disabled || isTaken}
                onClick={() => onJerseyChange(number)}
                className={`h-11 rounded-lg text-sm font-semibold tabular-nums transition-colors ${
                  isSelected
                    ? "bg-pitch-500 text-ink-900"
                    : isTaken
                      ? "cursor-not-allowed bg-ink-800 text-ink-500 line-through"
                      : "bg-ink-700 text-ink-100 hover:bg-ink-600"
                }`}
              >
                {number}
              </button>
            );
          })}
        </div>
        <p className="mt-2 text-sm text-ink-400">
          Crossed-out numbers are already taken on team {team}.
        </p>
      </div>
    </div>
  );
}

export { JerseyNumber };
