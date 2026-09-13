import type { ScoreData } from "@/components/MeetingScore";
import type { TranscriptEntry } from "./api-types";
import { clock, duration, plural } from "./format";
import { estimateSeconds, reasonText, type AnswerItem, type SilenceItem } from "./meeting";

/**
 * Lays a meeting out on a time axis from what the backend stores: transcript start
 * times and the times answers were logged. Bar lengths are estimated from word count,
 * because the backend doesn't store how long anyone spoke.
 */

export interface Timeline {
  startMs: number;
  span: number; // seconds
  human: { id: string; speaker: string; t: number; dur: number; text: string; at: string }[];
  agent: { sequence: number; t: number; dur: number; text: string; at: string; asker?: string }[];
  named: { id: string; t: number; text: string; speaker: string; reason: string; at: string }[];
}

export function timeline(transcript: TranscriptEntry[], answers: AnswerItem[], silences: SilenceItem[]): Timeline | null {
  const finals = transcript.filter((t) => t.is_final);
  const starts = [...finals.map((t) => Date.parse(t.spoken_at)), ...answers.map((a) => Date.parse(a.at))].filter((n) => !Number.isNaN(n));
  if (starts.length === 0) return null;
  const startMs = Math.min(...starts);
  const sec = (iso: string) => (Date.parse(iso) - startMs) / 1000;

  const human = finals.map((t) => ({ id: `t-${t.id}`, speaker: t.speaker, t: sec(t.spoken_at), dur: estimateSeconds(t.text), text: t.text, at: t.spoken_at }));
  const agent = answers.map((a) => ({ sequence: a.sequence, t: sec(a.at), dur: estimateSeconds(a.answer, 2.6), text: a.answer, at: a.at, asker: a.question?.speaker }));
  const named = silences
    .filter((s) => s.reason === "addressed, but no response was requested")
    .map((s) => {
      const line = s.utteranceId ? finals.find((t) => t.id === s.utteranceId) : undefined;
      return { id: line ? `t-${line.id}` : `s-${s.sequence}`, t: sec(line?.spoken_at ?? s.at), text: s.text, speaker: s.speaker, reason: s.reason, at: line?.spoken_at ?? s.at };
    });

  const end = Math.max(...human.map((h) => h.t + h.dur), ...agent.map((a) => a.t + a.dur), 1);
  return { startMs, span: Math.ceil(end + 2), human, agent, named };
}

function tickStep(span: number): number {
  if (span <= 90) return 15;
  if (span <= 180) return 30;
  if (span <= 6 * 60) return 60;
  if (span <= 16 * 60) return 120;
  if (span <= 40 * 60) return 300;
  return 600;
}

export function scoreData(tl: Timeline, agent: string): ScoreData {
  const step = tickStep(tl.span);
  const withSeconds = step < 60;
  const ticks = Array.from({ length: Math.floor(tl.span / step) + 1 }, (_, i) => ({
    t: i * step,
    label: clock(tl.startMs + i * step * 1000, withSeconds),
  }));

  const talk = new Map<string, number>();
  for (const h of tl.human) talk.set(h.speaker, (talk.get(h.speaker) ?? 0) + h.dur);
  const lanes = [...talk.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([name, seconds]) => ({ id: name, name, short: name.split(/\s+/)[0] ?? name, talk: duration(seconds) }));

  const answered = tl.agent.length;
  const quiet = Math.max(0, tl.human.length - answered);
  const summary =
    answered > 0
      ? `${agent} answered ${plural(answered, "time")} and stayed quiet through the other ${plural(quiet, "line")}.`
      : `${agent} stayed quiet through all ${plural(tl.human.length, "line")}.`;

  return {
    start: new Date(tl.startMs).toISOString(),
    length: tl.span,
    ticks,
    tickStep: step,
    lanes,
    voices: tl.human.map((h) => ({ id: h.id, lane: h.speaker, t: h.t, dur: h.dur, clock: clock(h.at, true), text: h.text })),
    spoke: tl.agent.map((a) => ({
      id: `a-${a.sequence}`,
      turnId: String(a.sequence),
      t: a.t,
      dur: a.dur,
      clock: clock(a.at, true),
      text: a.text,
      heading: a.asker ? `${agent} answered ${a.asker}` : `${agent} answered`,
    })),
    heldBack: tl.named.map((n) => ({ id: n.id, t: n.t, clock: clock(n.at, true), text: n.text, heading: `${n.speaker}. ${agent} held back`, note: reasonText(n.reason, agent) })),
    chat: [],
    agentName: agent,
    summary,
    note: "Bar lengths are estimated from word counts.",
  };
}
