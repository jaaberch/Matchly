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

export interface VenueRef {
  id: string;
  name: string;
  location: string;
}

export interface FieldRef {
  id: string;
  name: string;
}

export interface MatchSummary {
  id: string;
  title: string | null;
  status: MatchStatus;
  starts_at: string;
  ends_at: string;
  join_code: string;
  venue: VenueRef;
  field: FieldRef;
  player_count: number;
  highlight_count: number;
  video_url: string | null;
}

export interface MatchPlayer {
  id: string;
  user_id: string;
  name: string;
  avatar: string | null;
  team: Team;
  jersey_number: number;
  jersey_override: boolean;
  is_me: boolean;
}

export interface VideoRef {
  id: string;
  status: string;
  duration: number | null;
}

export interface MatchDetail extends MatchSummary {
  players: MatchPlayer[];
  video: VideoRef | null;
  created_at: string;
}

/** The public QR landing payload. Carries no player identities by design. */
export interface MatchJoinPreview {
  match_id: string;
  title: string | null;
  status: MatchStatus;
  starts_at: string;
  ends_at: string;
  venue_name: string;
  field_name: string;
  recording_disclosure: string | null;
  joinable: boolean;
  taken_jerseys: Record<Team, number[]>;
  team_sizes: Record<Team, number>;
  already_joined: boolean;
  my_team: Team | null;
  my_jersey_number: number | null;
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
