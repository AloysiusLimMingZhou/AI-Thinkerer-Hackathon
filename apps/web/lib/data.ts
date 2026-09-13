import { allHands } from "./fixtures/all-hands";
import { adyenRenewal } from "./fixtures/adyen-renewal";
import { designCrit } from "./fixtures/design-crit";
import { growthPlanning } from "./fixtures/growth-planning";
import { paymentsWeekly } from "./fixtures/payments-weekly";
import { platformStandup } from "./fixtures/platform-standup";
import { webhooksReview } from "./fixtures/webhooks-review";
import { dayKey, shortDay } from "./format";
import { AGENT_NAME, person } from "./people";
import { AGENT, type AgentTurn, type Meeting, type Person, type SilenceReason, type Utterance } from "./types";

/**
 * Data access for the dashboard. Everything reads from fixtures today; swap these
 * functions for calls to apps/api (GET /sessions, /sessions/{id}, /sessions/{id}/minutes).
 */

/** "Now" for the fixtures, so the demo reads the same on any day. */
export const NOW = "2026-09-13T09:30:00+08:00";

const meetings: Meeting[] = [paymentsWeekly, designCrit, platformStandup, adyenRenewal, growthPlanning, allHands, webhooksReview].sort(
  (a, b) => Date.parse(b.start) - Date.parse(a.start),
);

/** Newest first. */
export function listMeetings(): Meeting[] {
  return meetings;
}

export function getMeeting(id: string): Meeting | undefined {
  return meetings.find((m) => m.id === id);
}

/** The meetings either side of `id`, in time order. */
export function neighbours(id: string): { earlier?: Meeting; later?: Meeting } {
  const i = meetings.findIndex((m) => m.id === id);
  return { earlier: meetings[i + 1], later: i > 0 ? meetings[i - 1] : undefined };
}

export function lengthSeconds(m: Meeting): number {
  return (Date.parse(m.end) - Date.parse(m.start)) / 1000;
}

export function utterance(m: Meeting, id: string | undefined): Utterance | undefined {
  return id ? m.utterances.find((u) => u.id === id) : undefined;
}

/** Turns where the agent spoke out loud (answers and deferrals, not the chat hello). */
export function spokenTurns(m: Meeting): AgentTurn[] {
  return m.turns.filter((t) => t.kind !== "announcement");
}

export function onAirSeconds(m: Meeting): number {
  return m.utterances.filter((u) => u.speaker === AGENT && u.channel === "voice").reduce((s, u) => s + u.dur, 0);
}

export interface GateTally {
  heard: number;
  spoke: number;
  quiet: number;
  reasons: Record<SilenceReason, number>;
}

/** What the speaking gate decided for every human voice utterance. */
export function gateTally(m: Meeting): GateTally {
  const triggers = new Set(m.turns.map((t) => t.trigger).filter(Boolean));
  const reasons: Record<SilenceReason, number> = { not_addressed: 0, no_question: 0, human_answering: 0, cooldown: 0 };
  let heard = 0;
  let spoke = 0;
  for (const u of m.utterances) {
    if (u.speaker === AGENT || u.channel !== "voice") continue;
    heard += 1;
    if (triggers.has(u.id)) spoke += 1;
    else reasons[u.silence ?? "not_addressed"] += 1;
  }
  return { heard, spoke, quiet: heard - spoke, reasons };
}

export const SILENCE_LABELS: Record<SilenceReason, string> = {
  not_addressed: "Nobody was talking to it",
  no_question: "Spoken to, but nothing to answer",
  human_answering: "Someone else answered first",
  cooldown: "It had just spoken twice in a row",
};

export interface SpeakerStat {
  person: Person;
  seconds: number;
  turns: number;
}

/** Humans who spoke, most talk time first. */
export function speakers(m: Meeting): SpeakerStat[] {
  const stats = new Map<string, SpeakerStat>();
  for (const u of m.utterances) {
    if (u.speaker === AGENT || u.channel !== "voice") continue;
    const s = stats.get(u.speaker) ?? { person: person(u.speaker), seconds: 0, turns: 0 };
    s.seconds += u.dur;
    s.turns += 1;
    stats.set(u.speaker, s);
  }
  return [...stats.values()].sort((a, b) => b.seconds - a.seconds);
}

export interface WaitingItem {
  meeting: Meeting;
  turn: AgentTurn;
  question: Utterance;
  askedBy: Person;
  summary: string;
  due?: string;
}

/** Questions the agent passed back to you, across all meetings, soonest due first. */
export function waitingOnYou(): WaitingItem[] {
  const items: WaitingItem[] = [];
  for (const m of meetings) {
    for (const t of m.turns) {
      if (t.kind !== "defer" || !t.flag) continue;
      const q = utterance(m, t.trigger);
      if (!q) continue;
      items.push({ meeting: m, turn: t, question: q, askedBy: person(q.speaker), summary: t.flag.summary, due: t.flag.due });
    }
  }
  return items.sort((a, b) => (a.due ?? "9999").localeCompare(b.due ?? "9999"));
}

export function waitingIn(m: Meeting): WaitingItem[] {
  return waitingOnYou().filter((w) => w.meeting.id === m.id);
}

export interface WeekSummary {
  sent: number;
  attended: number;
  notAdmitted: number;
  seconds: number;
  spoke: number;
  deferred: number;
}

export function weekSummary(): WeekSummary {
  const attended = meetings.filter((m) => m.status === "attended");
  return {
    sent: meetings.length,
    attended: attended.length,
    notAdmitted: meetings.length - attended.length,
    seconds: attended.reduce((s, m) => s + lengthSeconds(m), 0),
    spoke: attended.reduce((s, m) => s + spokenTurns(m).length, 0),
    deferred: attended.reduce((s, m) => s + m.turns.filter((t) => t.kind === "defer").length, 0),
  };
}

export interface DueStatus {
  overdue: boolean;
  text: string;
}

/** "Needed by Fri 18 Sep", or "Overdue since Fri 11 Sep" once NOW has passed it. */
export function dueStatus(due: string): DueStatus {
  const today = dayKey(NOW);
  if (due < today) return { overdue: true, text: `Overdue since ${shortDay(due)}` };
  if (due === today) return { overdue: false, text: "Needed today" };
  return { overdue: false, text: `Needed by ${shortDay(due)}` };
}

export function speakerName(speaker: string): string {
  return speaker === AGENT ? AGENT_NAME : person(speaker).name;
}
