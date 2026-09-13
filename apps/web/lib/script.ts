import { AGENT, type Meeting, type SilenceReason, type Utterance } from "./types";

/**
 * Fixture helper: turns a hand-written meeting script into timed utterances, the way
 * platforms/sim.py plays a YAML script. Times come from word counts, so a line's
 * duration always matches its length and the timeline stays honest.
 */

export interface LineOpts {
  /** Stable id, so turns, minutes and silences can point at the line. */
  id?: string;
  /** Extra silence before the line, in seconds (screen shares, people joining). */
  pause?: number;
  /** Override the usual gap after the previous line, in seconds. */
  gap?: number;
  /** Agent lines: finalised caption to first audible word, in seconds. */
  latency?: number;
  chat?: boolean;
  silence?: SilenceReason;
}

export type Line = [speaker: string, text: string, opts?: LineOpts];

/** Clean transcripts drop the ums and restarts, so effective pace is below raw speech (~150 wpm). */
const HUMAN_WORDS_PER_SEC = 2.05;
const AGENT_WORDS_PER_SEC = 2.6;
/** The aggregator waits for this much quiet before it finalises an utterance. */
const FINALISE_AFTER = 1.2;

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const round1 = (n: number) => Math.round(n * 10) / 10;

export function script(lines: Line[], { seed = 1, startAt = 4 } = {}): Utterance[] {
  const rand = mulberry32(seed);
  let cursor = startAt;

  return lines.map(([speaker, text, o = {}], i) => {
    const words = text.trim().split(/\s+/).length;
    const isAgent = speaker === AGENT;
    const pause = o.pause ?? 0;

    if (o.chat) {
      const t = cursor + pause + 0.8 + rand() * 1.5;
      cursor = t;
      return { id: o.id ?? `u${i + 1}`, speaker, t: round1(t), dur: 0, text, channel: "chat" };
    }

    const gap = isAgent
      ? FINALISE_AFTER + (o.latency ?? 2)
      : (o.gap ?? 0.6 + rand() * 1.6);
    const t = cursor + pause + gap;
    const pace = isAgent ? AGENT_WORDS_PER_SEC : HUMAN_WORDS_PER_SEC + (rand() - 0.5) * 0.5;
    const dur = Math.max(1.1, words / pace);
    cursor = t + dur;

    const u: Utterance = { id: o.id ?? `u${i + 1}`, speaker, t: round1(t), dur: round1(dur), text, channel: "voice" };
    if (o.silence) u.silence = o.silence;
    return u;
  });
}

type MeetingInput = Omit<Meeting, "end" | "utterances" | "agentJoinedAt" | "agentLeftAt"> & {
  lines: Line[];
  seed: number;
  /** Seconds of goodbyes after the last line. */
  tail?: number;
  /** Seconds before the first line (people trickling in). */
  lead?: number;
};

/** Builds a Meeting from a script, deriving end time and when the agent joined and left. */
export function defineMeeting({ lines, seed, tail = 6, lead = 4, ...rest }: MeetingInput): Meeting {
  const utterances = script(lines, { seed, startAt: lead });
  const last = utterances.reduce((m, u) => Math.max(m, u.t + u.dur), 0);
  const firstAgent = utterances.find((u) => u.speaker === AGENT);
  const length = Math.ceil(last + tail);
  const end = new Date(new Date(rest.start).getTime() + length * 1000);

  return {
    ...rest,
    end: toOffsetIso(end, rest.start),
    utterances,
    agentJoinedAt: firstAgent ? Math.max(0, round1(firstAgent.t - 7)) : undefined,
    agentLeftAt: round1(last + tail - 1),
  };
}

/** For meetings the agent never got into: only the invite and the wait. */
export function unattendedMeeting(
  input: Omit<Meeting, "end" | "utterances" | "turns" | "notableSilences" | "transcriptSource" | "status"> & {
    lobbyWait: number;
  },
): Meeting {
  const end = new Date(new Date(input.start).getTime() + input.lobbyWait * 1000);
  return {
    ...input,
    status: "not_admitted",
    end: toOffsetIso(end, input.start),
    transcriptSource: "none",
    utterances: [],
    turns: [],
    notableSilences: [],
  };
}

/** Formats a Date as ISO in the same UTC offset as `like` (e.g. +08:00). */
function toOffsetIso(d: Date, like: string): string {
  const m = like.match(/([+-])(\d{2}):(\d{2})$/);
  if (!m) return d.toISOString();
  const sign = m[1] === "-" ? -1 : 1;
  const offsetMin = sign * (Number(m[2]) * 60 + Number(m[3]));
  const local = new Date(d.getTime() + offsetMin * 60_000);
  return local.toISOString().replace(/\.\d{3}Z$/, `${m[1]}${m[2]}:${m[3]}`);
}
