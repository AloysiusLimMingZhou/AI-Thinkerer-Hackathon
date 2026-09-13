import type { BackendEvent, Bot, Citation, ContextNote, Session, TranscriptEntry } from "./api-types";

/**
 * Turns what the backend stores (sessions, bot state, transcript, event log) into what
 * the dashboard shows. The backend keeps answers and briefing notes only in its event
 * log, so this is where they are reassembled.
 */

export const DEFAULT_AGENT = "Alloy";
export const DEFAULT_OWNER = "Aloy";

/* Bot state ------------------------------------------------------------------ */

export type Tone = "live" | "waiting" | "done" | "problem";

export interface BotStateInfo {
  label: string;
  detail: string;
  tone: Tone;
}

/** Launch outcomes that won't change on their own. */
const FINAL_STATES = new Set(["done", "fatal", "call_ended", "deleted", "failed", "needs_attention"]);

export function isFinal(bot: Bot | null): boolean {
  return !!bot && FINAL_STATES.has(bot.state);
}

export function inCall(bot: Bot | null): boolean {
  return !!bot && bot.state.startsWith("in_call");
}

/** Whether the page should keep polling: a bot is on its way, in the call, or the meeting is active. */
export function isLive(session: Session, bot: Bot | null): boolean {
  if (bot) return !isFinal(bot);
  return session.status === "active";
}

export function botState(bot: Bot | null, agent: string, when?: string): BotStateInfo {
  if (!bot) {
    return { label: "Not sent yet", detail: `${agent} hasn't been asked to join this meeting.`, tone: "waiting" };
  }
  const name = `${agent} (AI delegate)`;
  switch (bot.state) {
    case "queued":
      return { label: "Queued", detail: "The request is saved. The backend is asking Recall to create the bot.", tone: "waiting" };
    case "creating":
      return { label: "Creating the bot", detail: "Waiting for Recall to confirm the bot exists.", tone: "waiting" };
    case "retrying":
      return { label: "Retrying", detail: "Recall was busy. The backend will try again shortly.", tone: "waiting" };
    case "scheduled":
      return when
        ? { label: `Scheduled for ${when}`, detail: `Recall will send ${name} to the meeting at that time.`, tone: "waiting" }
        : { label: "On its way", detail: `Recall has the bot and is sending ${name} to the meeting.`, tone: "waiting" };
    case "joining_call":
      return { label: "Joining the call", detail: `${name} is opening the meeting link.`, tone: "waiting" };
    case "in_waiting_room":
      return { label: "Waiting to be let in", detail: `Someone in the meeting needs to admit ${name}.`, tone: "waiting" };
    case "in_call_not_recording":
      return { label: "In the call, not recording", detail: "It's in, but the host hasn't allowed recording yet, so it can't transcribe.", tone: "waiting" };
    case "recording_permission_denied":
      return { label: "Recording not allowed", detail: "The host declined recording, so it can't transcribe or answer.", tone: "problem" };
    case "in_call_recording":
      return { label: "In the call", detail: `Listening and transcribing. It answers only when someone says "${agent}" and asks something.`, tone: "live" };
    case "call_ended":
      return { label: "Left the call", detail: "The transcript and minutes follow once Recall finishes processing.", tone: "done" };
    case "done":
      return { label: "Finished", detail: "Recording and transcript are complete.", tone: "done" };
    case "fatal":
      return { label: "Couldn't stay in the call", detail: bot.error || "Recall reported a fatal error.", tone: "problem" };
    case "failed":
      return { label: "Couldn't launch", detail: bot.error || "Recall rejected the request.", tone: "problem" };
    case "needs_attention":
      return {
        label: "Needs attention",
        detail: `${bot.error || "The outcome is unclear."} Check Recall's bot explorer before trying again, and use a new meeting for a fresh launch.`,
        tone: "problem",
      };
    case "deleted":
      return { label: "Cancelled", detail: "The bot was cancelled before it joined.", tone: "done" };
    default:
      return { label: bot.state, detail: "Recall reported this state.", tone: "waiting" };
  }
}

/* Meeting link ---------------------------------------------------------------- */

export function platformOf(url: string | null): { name: string; host: string } | null {
  if (!url) return null;
  try {
    const host = new URL(url).hostname;
    if (host === "meet.google.com") return { name: "Google Meet", host };
    if (host === "zoom.us" || host.endsWith(".zoom.us")) return { name: "Zoom", host };
    if (host.startsWith("teams.")) return { name: "Microsoft Teams", host };
    return { name: host, host };
  } catch {
    return null;
  }
}

/* Answers, silences and briefing, from the event log ---------------------------- */

interface UtterancePayload {
  id?: string;
  speaker?: string;
  text?: string;
  spoken_at?: string;
}

export type VoiceOutcome = "played" | "queued" | "failed" | "none";

export interface AnswerItem {
  sequence: number;
  at: string;
  question?: { id?: string; speaker: string; text: string; at: string };
  answer: string;
  reason: string;
  citations: Citation[];
  voice: VoiceOutcome;
}

export interface SilenceItem {
  sequence: number;
  at: string;
  utteranceId?: string;
  speaker: string;
  text: string;
  reason: string;
}

export function answersFrom(events: BackendEvent[]): AnswerItem[] {
  const answers: AnswerItem[] = [];
  const byVoiceId = new Map<string, AnswerItem>();
  let lastUtterance: UtterancePayload | null = null;
  let awaitingVoice: AnswerItem | null = null;

  for (const e of events) {
    const p = e.payload as Record<string, unknown>;
    if (e.type === "transcript.utterance") {
      lastUtterance = p as UtterancePayload;
    } else if (e.type === "agent.decision" && p.action === "answer" && typeof p.answer === "string") {
      const item: AnswerItem = {
        sequence: e.sequence,
        at: e.created_at,
        question: lastUtterance?.text
          ? { id: lastUtterance.id, speaker: lastUtterance.speaker ?? "Someone", text: lastUtterance.text, at: lastUtterance.spoken_at ?? e.created_at }
          : undefined,
        answer: p.answer,
        reason: String(p.reason ?? ""),
        citations: Array.isArray(p.citations) ? (p.citations as Citation[]) : [],
        voice: "none",
      };
      answers.push(item);
      awaitingVoice = item;
    } else if (e.type === "voice.queued" && awaitingVoice) {
      awaitingVoice.voice = "queued";
      if (typeof p.id === "string") byVoiceId.set(p.id, awaitingVoice);
      awaitingVoice = null;
    } else if ((e.type === "voice.played" || e.type === "voice.failed") && typeof p.id === "string") {
      const item = byVoiceId.get(p.id);
      if (item) item.voice = e.type === "voice.played" ? "played" : "failed";
    }
  }
  return answers;
}

/** Silent decisions the backend logged (the manual caption endpoint logs them; live meetings log answers only). */
export function silencesFrom(events: BackendEvent[]): SilenceItem[] {
  const out: SilenceItem[] = [];
  let lastUtterance: UtterancePayload | null = null;
  for (const e of events) {
    const p = e.payload as Record<string, unknown>;
    if (e.type === "transcript.utterance") lastUtterance = p as UtterancePayload;
    else if (e.type === "agent.decision" && p.action === "stay_silent" && lastUtterance?.text) {
      out.push({
        sequence: e.sequence,
        at: e.created_at,
        utteranceId: lastUtterance.id,
        speaker: lastUtterance.speaker ?? "Someone",
        text: lastUtterance.text,
        reason: String(p.reason ?? ""),
      });
    }
  }
  return out;
}

/** Audio the dashboard sent with "Say in the meeting". The backend doesn't log its text. */
export function manualPlaybacks(events: BackendEvent[]): { sequence: number; at: string; outcome: "played" | "failed" }[] {
  const answerVoiceIds = new Set<string>();
  for (const e of events) if (e.type === "voice.queued" && typeof e.payload.id === "string") answerVoiceIds.add(e.payload.id);
  return events
    .filter((e) => (e.type === "voice.played" || e.type === "voice.failed") && typeof e.payload.id === "string" && !answerVoiceIds.has(e.payload.id as string))
    .map((e) => ({ sequence: e.sequence, at: e.created_at, outcome: e.type === "voice.played" ? "played" : "failed" }));
}

export function briefingFrom(events: BackendEvent[]): ContextNote[] {
  const notes: ContextNote[] = [];
  for (const e of events) {
    if (e.type !== "context.added" && e.type !== "context.imported") continue;
    const list = (e.payload as { notes?: ContextNote[] }).notes;
    if (Array.isArray(list)) notes.push(...list);
  }
  return notes;
}

/** Plain-language version of the backend's gate reasons. */
export function reasonText(reason: string, agent: string): string {
  switch (reason) {
    case "wake name and response request detected":
      return `Someone said "${agent}" and asked a question.`;
    case "wake phrase followed by same-speaker question":
      return `Someone said "${agent}", then asked a question straight after.`;
    case "manual override":
      return "Answered because it was asked to from the dashboard.";
    case "wake name not detected":
      return `Nobody said "${agent}".`;
    case "addressed, but no response was requested":
      return `Someone said "${agent}" but didn't ask anything.`;
    case "waiting for final caption":
      return "The caption wasn't finished yet.";
    default:
      return reason;
  }
}

/* Transcript with Alloy's answers merged in -------------------------------------- */

export interface Line {
  id: string;
  at: string;
  speaker: string;
  text: string;
  agent: boolean;
  final: boolean;
}

export function mergedTranscript(transcript: TranscriptEntry[], answers: AnswerItem[], agent: string): Line[] {
  const lines: Line[] = transcript
    .filter((t) => t.is_final)
    .map((t) => ({ id: `t-${t.id}`, at: t.spoken_at, speaker: t.speaker, text: t.text, agent: false, final: true }));
  for (const a of answers) {
    lines.push({ id: `a-${a.sequence}`, at: a.at, speaker: agent, text: a.answer, agent: true, final: true });
  }
  return lines.sort((x, y) => Date.parse(x.at) - Date.parse(y.at));
}

/** Rough speaking time from word count. The backend stores start times only. */
export function estimateSeconds(text: string, wordsPerSecond = 2.4): number {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(1.2, words / wordsPerSecond);
}

/* Activity log --------------------------------------------------------------------- */

export interface ActivityItem {
  sequence: number;
  at: string;
  title: string;
  detail?: string;
  tone: Tone | "quiet";
}

export function activityFrom(events: BackendEvent[], agent: string, stateLabel: (state: string) => string): ActivityItem[] {
  const out: ActivityItem[] = [];
  for (const e of events) {
    const p = e.payload as Record<string, unknown>;
    const base = { sequence: e.sequence, at: e.created_at };
    switch (e.type) {
      case "session.created":
        out.push({ ...base, title: "Meeting created", tone: "quiet" });
        break;
      case "context.added":
      case "context.imported": {
        const n = Array.isArray(p.notes) ? p.notes.length : 0;
        out.push({ ...base, title: n === 1 ? "Added a briefing note" : `Added ${n} briefing notes`, tone: "quiet" });
        break;
      }
      case "agent.decision":
        if (p.action === "answer") out.push({ ...base, title: `${agent} answered`, detail: reasonText(String(p.reason ?? ""), agent), tone: "live" });
        else out.push({ ...base, title: "Stayed quiet", detail: reasonText(String(p.reason ?? ""), agent), tone: "quiet" });
        break;
      case "voice.queued":
        out.push({ ...base, title: "Reply queued to play in the meeting", tone: "waiting" });
        break;
      case "voice.played":
        out.push({ ...base, title: "Audio finished playing in the meeting", detail: "Reported by the bot's audio page. Only people in the call can confirm they heard it.", tone: "live" });
        break;
      case "voice.failed":
        out.push({ ...base, title: "Audio couldn't play", tone: "problem" });
        break;
      case "voice.generated":
        out.push({ ...base, title: "Generated audio (not sent to the meeting)", tone: "quiet" });
        break;
      case "bot.scheduled":
        out.push({ ...base, title: "Recall created the bot", tone: "waiting" });
        break;
      case "bot.status":
        out.push({ ...base, title: stateLabel(String(p.state ?? "")), detail: p.sub_code ? `Recall: ${String(p.state)} (${String(p.sub_code)})` : `Recall: ${String(p.state)}`, tone: "waiting" });
        break;
      case "transcript.saved":
        out.push({ ...base, title: "Saved the final transcript", detail: typeof p.utterances === "number" ? `${p.utterances} lines from Recall` : undefined, tone: "done" });
        break;
      case "minutes.generated":
        out.push({ ...base, title: "Wrote the minutes", tone: "done" });
        break;
      case "coach.suggestion":
        out.push({ ...base, title: "Made a private suggestion", tone: "quiet" });
        break;
      case "transcript.utterance":
        break; // shown in the transcript instead
      default:
        out.push({ ...base, title: e.type.replace(/[._]/g, " "), tone: e.type.endsWith("failed") ? "problem" : "quiet" });
    }
  }
  return out;
}
