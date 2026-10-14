/**
 * Response shapes of the Alloy backend (src/meeting_agent/models.py and recall_api.py).
 * Keep in step with the backend; docs/BACKEND_HANDOFF.md is the contract.
 */

export type SessionStatus = "created" | "active" | "ended";

export interface Session {
  id: string;
  title: string;
  owner_name: string;
  agent_name: string;
  meeting_url: string | null;
  status: SessionStatus;
  created_at: string;
}

export interface ContextNote {
  id: string;
  source: string;
  title: string;
  content: string;
  created_at: string;
}

export interface TranscriptEntry {
  id: string;
  speaker: string;
  text: string;
  is_final: boolean;
  spoken_at: string;
}

export interface Citation {
  filename?: string | null;
  locator?: string | null;
  quote?: string | null;
  id: string;
  source: string;
  title: string;
}

export interface AgentDecision {
  action: "stay_silent" | "answer" | "defer";
  reason: string;
  answer?: string | null;
  citations?: Citation[];
}

export interface Minutes {
  session_id: string;
  content: string;
  updated_at: string;
}

/** A row of recall_bots, as GET /sessions/{id}/bot returns it. */
export interface Bot {
  session_id: string;
  bot_id: string | null;
  launch_key: string;
  state: string;
  join_at: string | null;
  error: string | null;
  last_status_at: string | null;
  media_expires: number;
}

export interface BackendEvent {
  sequence: number;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface RecallStatus {
  workspace: string;
  region: string;
  missing: string[];
  configured: boolean;
  calendar_count: number;
  note: string;
}

export interface Health {
  status: "ok";
  openai_configured: boolean;
  elevenlabs_configured: boolean;
}

export interface DiscordStatus {
  configured: boolean;
  missing: string[];
  gateway: string;
  voice_attendance_available: boolean;
}

export interface UnansweredQuestion {
  id: string;
  question: string;
  speaker: string;
  state: string;
  error: string | null;
  thread_id: string | null;
}
