/**
 * View model for the dashboard.
 *
 * Mirrors the shared contract in src/meeting_agent/types.py (MeetingInfo, Transcript,
 * QAEntry, Answer, Minutes, ContextChunk) so the fixtures in lib/fixtures can be swapped
 * for GET /sessions/{id} and /sessions/{id}/minutes without touching any component.
 */

export type PersonId = string;

/** The agent's own speaker id in utterances. */
export const AGENT = "agent";

export interface Person {
  id: PersonId;
  name: string;
  /** What colleagues call them, when it isn't simply the first word ("Mei Ling", "Wei Jie"). */
  short?: string;
  role: string;
  /** Set for people from outside the company. */
  org?: string;
}

export type SourceKind = "slack" | "drive" | "calendar";

/** A ContextChunk{source, author, ts, text, url} the agent quoted in an answer. */
export interface Citation {
  kind: SourceKind;
  source: string;
  author?: string;
  /** ISO timestamp. */
  ts?: string;
  /** The passage the answer relied on, verbatim. */
  text: string;
  url?: string;
}

/** Why the speaking gate kept the agent quiet for an utterance. */
export type SilenceReason =
  | "not_addressed" // nobody spoke to the agent
  | "no_question" // spoken to, but there was nothing to answer
  | "human_answering" // a person started answering first
  | "cooldown"; // it had just spoken twice in a row

export interface Utterance {
  id: string;
  speaker: PersonId | typeof AGENT;
  /** Seconds from the scheduled start. */
  t: number;
  /** Seconds. Zero for chat messages. */
  dur: number;
  text: string;
  channel: "voice" | "chat";
  /** Gate outcome, set on human voice utterances that did not trigger a turn. */
  silence?: SilenceReason;
}

/** One thing the agent said, and why. Mirrors QAEntry + Answer. */
export interface AgentTurn {
  id: string;
  /** The agent's own line in the transcript. */
  utteranceId: string;
  kind: "answer" | "defer" | "announcement";
  /** Utterance id of the question it responded to. */
  trigger?: string;
  /** The three gate stages, as they fired. */
  gate?: {
    /** The wake phrase as it appeared in the captions. */
    heard: string;
    /** What made it expect a response: "Question", "Request", "Hand-off". */
    signal: string;
    /** Stage-3 confirmation score, 0..1. */
    confirmed: number;
  };
  /** Brain confidence in the answer, 0..1. Below 0.5 it defers. */
  confidence?: number;
  /** Finalised caption to first audible word. */
  latencyMs?: number;
  citations: Citation[];
  /** What it looked through, shown when it had nothing to cite. */
  searched?: string;
  /** Set on deferrals: the item added to your list. */
  flag?: { summary: string; due?: string };
}

/** A moment the gate came close to firing and correctly stayed quiet. */
export interface NotableSilence {
  utteranceId: string;
  reason: SilenceReason;
  note: string;
}

export interface ActionItem {
  owner: PersonId | "you";
  task: string;
  /** ISO date. */
  due?: string;
  /** Utterance id the item came from. */
  source?: string;
}

export interface Minutes {
  tldr: string;
  decisions: { text: string; source?: string }[];
  actions: ActionItem[];
  openQuestions: { text: string; askedBy?: PersonId; source?: string; note?: string }[];
  topics: { title: string; notes: string[] }[];
  /** Seconds after the meeting ended that the minutes were ready. */
  readyAfter: number;
}

/** One entry of the context pack the agent brought into the meeting. */
export interface ContextSource {
  kind: SourceKind;
  label: string;
  detail: string;
}

export interface Meeting {
  id: string;
  title: string;
  /** ISO, scheduled start. Utterance times are offsets from this. */
  start: string;
  /** ISO, when the call ended (or when the agent gave up waiting). */
  end: string;
  platform: "Google Meet";
  host: PersonId;
  /** People on the invite who attended. */
  attendees: PersonId[];
  /** For large calls: everyone connected, including listeners not listed. */
  audienceSize?: number;
  status: "attended" | "not_admitted";
  agentJoinedAt?: number;
  agentLeftAt?: number;
  /** Seconds spent in the waiting room before giving up. */
  lobbyWait?: number;
  transcriptSource: "scribe" | "captions" | "none";
  context: ContextSource[];
  utterances: Utterance[];
  turns: AgentTurn[];
  notableSilences: NotableSilence[];
  minutes?: Minutes;
}
