import type { MatchStatus } from "@/lib/types";

/**
 * Match status is the single most-asked question in the product — by players
 * ("are my highlights ready?") and by venue staff ("is it recording?"). It gets
 * one consistent, colour-coded component everywhere it appears.
 */
const STATUS: Record<MatchStatus, { label: string; className: string }> = {
  SCHEDULED: { label: "Scheduled", className: "bg-ink-600 text-ink-200" },
  CHECK_IN: { label: "Check-in open", className: "bg-sky-500/15 text-sky-300" },
  RECORDING: { label: "Recording", className: "bg-red-500/15 text-red-300" },
  UPLOADING: { label: "Uploading", className: "bg-amber-500/15 text-amber-300" },
  PROCESSING: { label: "Processing", className: "bg-violet-500/15 text-violet-300" },
  READY: { label: "Ready", className: "bg-pitch-500/15 text-pitch-300" },
  FAILED: { label: "Failed", className: "bg-red-600/20 text-red-300" },
};

export function StatusBadge({ status }: { status: MatchStatus }) {
  const { label, className } = STATUS[status];
  const live = status === "RECORDING";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${className}`}
    >
      {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}
      {label}
    </span>
  );
}
