/** Display formatting. Kept in one place so dates and scores read the same everywhere. */

/** `865` → `14:25`, matching how a timestamp is spoken about in football. */
export function formatClock(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safe / 60);
  const remainder = safe % 60;
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

export function formatDuration(seconds: number): string {
  return `${Math.round(seconds)}s`;
}

export function formatMatchDate(iso: string, locale = "en-GB"): string {
  const date = new Date(iso);
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();

  const time = date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return `Today · ${time}`;

  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  if (date.toDateString() === tomorrow.toDateString()) return `Tomorrow · ${time}`;

  return `${date.toLocaleDateString(locale, { day: "numeric", month: "short" })} · ${time}`;
}

/** A 0–1 confidence rendered as a percentage for the highlight card. */
export function formatScore(score: number): string {
  return `${Math.round(score * 100)}%`;
}

export function formatPhone(phone: string): string {
  // +212612345678 → +212 612 345 678
  const match = phone.match(/^(\+\d{3})(\d{3})(\d{3})(\d{3})$/);
  return match ? `${match[1]} ${match[2]} ${match[3]} ${match[4]}` : phone;
}
