import type { MatchPlayer, Team } from "@/lib/types";

/** The two squads side by side, each player shown by shirt number. */
export function TeamRoster({ players }: { players: MatchPlayer[] }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <TeamColumn team="A" players={players.filter((p) => p.team === "A")} />
      <TeamColumn team="B" players={players.filter((p) => p.team === "B")} />
    </div>
  );
}

function TeamColumn({ team, players }: { team: Team; players: MatchPlayer[] }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-300">
        Team {team}
        <span className="ml-1.5 text-ink-400">({players.length})</span>
      </h3>
      {players.length === 0 ? (
        <p className="text-sm text-ink-400">Nobody yet</p>
      ) : (
        <ul className="space-y-1.5">
          {players.map((player) => (
            <li key={player.id} className="flex items-center gap-2">
              <JerseyNumber number={player.jersey_number} highlight={player.is_me} />
              <span
                className={`truncate text-sm ${player.is_me ? "font-semibold text-ink-100" : "text-ink-200"}`}
              >
                {player.name}
                {player.is_me && <span className="ml-1 text-pitch-400">(you)</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function JerseyNumber({
  number,
  highlight = false,
}: {
  number: number;
  highlight?: boolean;
}) {
  return (
    <span
      className={`grid h-6 w-6 shrink-0 place-items-center rounded text-xs font-bold tabular-nums ${
        highlight ? "bg-pitch-500 text-ink-900" : "bg-ink-600 text-ink-100"
      }`}
    >
      {number}
    </span>
  );
}
