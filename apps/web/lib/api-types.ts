/**
 * Response shapes of the Alloy backend (src/meeting_agent/models.py and recall_api.py).
 * Keep in step with the backend; docs/BACKEND_HANDOFF.md is the contract.
 */

export type SessionStatus = "created" | "active" | "ended";

export interface Session {
  id: string;
  platform: 'google_meet' | 'discord';
  purpose: 'meeting' | 'briefing';
  source_briefing_id: string | null;
  briefing_ready: boolean;
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

export interface Finalization {
  session_id: string;
  state: "idle" | "processing" | "ready" | "failed" | "pending_budget";
  error: string | null;
}

export interface UnansweredQuestion {
  id: string;
  question: string;
  speaker: string;
  state: string;
  error: string | null;
  thread_id: string | null;
}


export interface VoiceHealth { gateway: boolean; connection: boolean; decoder: boolean; receiver: boolean; player: boolean }
export interface DiscordAttendance {
 session_id: string; guild_id: string; channel_id: string; generation: string;
 state: 'joining' | 'active' | 'leaving' | 'ended' | 'interrupted' | 'failed' | 'budget_stopped';
 health: VoiceHealth; muted: boolean; introduction: string; error: string | null; started_at: string; ended_at: string | null;
}
export interface DiscordAttendanceStatus {
 attendance: DiscordAttendance | null; worker_health: VoiceHealth; missing: string[]; voice_attendance_available: boolean;
}
export interface BudgetStatus {
 month: string; timezone: string; reset_at: string; soft_limit_micro_usd: number; hard_limit_micro_usd: number;
 settled_micro_usd: number; held_micro_usd: number; available_micro_usd: number;
 uncertain_count: number; soft_warning: boolean; last_denied: boolean; price_version: string; scope: string;
 providers: Record<string,{settled_micro_usd:number;held_micro_usd:number}>;
}
