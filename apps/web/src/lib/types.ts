/**
 * Wire types.
 *
 * These mirror the API's Pydantic schemas. Kept hand-written for now because the
 * surface is small; once it grows, generate them from `/openapi.json` rather than
 * letting the two drift.
 */

export type UserRole = "PLAYER" | "VENUE_OPERATOR" | "ADMIN";

export type MatchStatus =
  | "SCHEDULED"
  | "CHECK_IN"
  | "RECORDING"
  | "UPLOADING"
  | "PROCESSING"
  | "READY"
  | "FAILED";

export type Team = "A" | "B";

export type HighlightType =
  | "GOAL_AREA_ACTION"
  | "HIGH_INTENSITY"
  | "CELEBRATION"
  | "TEAM_BUILDUP"
  | "GENERIC";

export interface User {
  id: string;
  name: string;
  phone: string;
  avatar: string | null;
  role: UserRole;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface RequestOtpResult {
  challenge_id: string;
  phone: string;
  expires_at: string;
  dev_code: string | null;
}

/** Present from Phase 2 onwards. */
export interface MatchSummary {
  id: string;
  title: string | null;
  status: MatchStatus;
  starts_at: string;
  ends_at: string;
  join_code: string;
  venue_name: string;
  field_name: string;
  player_count: number;
  highlight_count: number;
  video_url: string | null;
}

/** Present from Phase 4 onwards. */
export interface Highlight {
  id: string;
  match_id: string;
  player_id: string | null;
  start_time: number;
  end_time: number;
  score: number;
  type: HighlightType;
  video_url: string | null;
  video_url_vertical: string | null;
  thumbnail_url: string | null;
  signals: Record<string, number>;
}

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  has_next: boolean;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
}
