import { spokenTurns, speakerName, utterance, waitingIn } from "./data";
import { clock, longDay, shortDay, vttTime, wallClock } from "./format";
import { AGENT_NAME, OWNER, person } from "./people";
import type { Meeting } from "./types";

export const TRANSCRIPT_FORMATS = {
  txt: { label: "Plain text", ext: "txt", mime: "text/plain; charset=utf-8" },
  md: { label: "Markdown", ext: "md", mime: "text/markdown; charset=utf-8" },
  vtt: { label: "Subtitles (WebVTT)", ext: "vtt", mime: "text/vtt; charset=utf-8" },
  json: { label: "JSON", ext: "json", mime: "application/json; charset=utf-8" },
} as const;

export type TranscriptFormat = keyof typeof TRANSCRIPT_FORMATS;

export function isTranscriptFormat(f: string | null): f is TranscriptFormat {
  return f !== null && f in TRANSCRIPT_FORMATS;
}

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

export function exportFilename(m: Meeting, kind: "transcript" | "minutes", ext: string): string {
  return `${m.start.slice(0, 10)}-${slug(m.title)}-${kind}.${ext}`;
}

function dateLine(m: Meeting): string {
  const w = wallClock(m.start);
  return `${longDay(m.start)} ${w.year}, ${clock(m.start)}–${clock(m.end)}, ${m.platform}`;
}

const SOURCE_NOTE = {
  scribe: "Transcribed from the recording by ElevenLabs Scribe. Speaker names matched to Meet captions.",
  captions: "From Meet's live captions. The recording hasn't been transcribed yet.",
  none: "No transcript.",
} as const;

export function transcriptTxt(m: Meeting): string {
  const lines = m.utterances.map((u) => {
    const who = speakerName(u.speaker) + (u.channel === "chat" ? " (in chat)" : "");
    return `[${clock(m.start, u.t, true)}] ${who}: ${u.text}`;
  });
  return [m.title, dateLine(m), SOURCE_NOTE[m.transcriptSource], "", ...lines, ""].join("\n");
}

export function transcriptMarkdown(m: Meeting): string {
  const out = [`# ${m.title}`, "", `${dateLine(m)}. ${SOURCE_NOTE[m.transcriptSource]}`, ""];
  let prev = "";
  for (const u of m.utterances) {
    const who = speakerName(u.speaker) + (u.channel === "chat" ? " (in chat)" : "");
    if (who !== prev) out.push(`**${who}**, ${clock(m.start, u.t, true)}  `);
    out.push(u.text, "");
    prev = who;
  }
  return out.join("\n");
}

export function transcriptVtt(m: Meeting): string {
  const cues = m.utterances
    .filter((u) => u.channel === "voice")
    .map((u, i) => `${i + 1}\n${vttTime(u.t)} --> ${vttTime(u.t + u.dur)}\n<v ${speakerName(u.speaker)}>${u.text}`);
  return ["WEBVTT", "", `NOTE ${m.title}, ${dateLine(m)}`, "", cues.join("\n\n"), ""].join("\n");
}

export function transcriptJson(m: Meeting): string {
  return JSON.stringify(
    {
      meeting: { id: m.id, title: m.title, start: m.start, end: m.end, platform: m.platform, transcriptSource: m.transcriptSource },
      utterances: m.utterances.map((u) => ({
        id: u.id,
        at: clock(m.start, u.t, true),
        offsetSeconds: u.t,
        durationSeconds: u.dur,
        speaker: speakerName(u.speaker),
        channel: u.channel,
        text: u.text,
      })),
      agentTurns: m.turns.map((t) => ({ id: t.id, kind: t.kind, utterance: t.utteranceId, question: t.trigger, citations: t.citations })),
    },
    null,
    2,
  );
}

export function renderTranscript(m: Meeting, format: TranscriptFormat): string {
  switch (format) {
    case "txt":
      return transcriptTxt(m);
    case "md":
      return transcriptMarkdown(m);
    case "vtt":
      return transcriptVtt(m);
    case "json":
      return transcriptJson(m);
  }
}

function ownerName(owner: string): string {
  return owner === "you" ? OWNER.name : person(owner).name;
}

/** Minutes as Markdown, for "Copy minutes" and the .md download. */
export function minutesMarkdown(m: Meeting): string {
  const mins = m.minutes;
  const out = [`# ${m.title}: minutes`, "", `${dateLine(m)}. Hosted by ${person(m.host).name}. ${AGENT_NAME} attended for ${OWNER.name}.`, ""];
  if (!mins) return [...out, "No minutes: the agent didn't get into this meeting.", ""].join("\n");

  out.push("## Summary", "", mins.tldr, "");

  const waiting = waitingIn(m);
  if (waiting.length) {
    out.push(`## Waiting on ${OWNER.short}`, "");
    for (const w of waiting) {
      out.push(`- ${w.summary}. Asked by ${w.askedBy.name} at ${clock(m.start, w.question.t)}${w.due ? `, needed by ${shortDay(w.due)}` : ""}.`);
    }
    out.push("");
  }

  if (mins.decisions.length) {
    out.push("## Decisions", "", ...mins.decisions.map((d) => `- ${d.text}`), "");
  }
  if (mins.actions.length) {
    out.push("## Action items", "", ...mins.actions.map((a) => `- [ ] ${ownerName(a.owner)}: ${a.task}${a.due ? ` (by ${shortDay(a.due)})` : ""}`), "");
  }
  if (mins.openQuestions.length) {
    out.push("## Open questions", "", ...mins.openQuestions.map((q) => `- ${q.text}${q.note ? ` ${q.note}` : ""}`), "");
  }
  if (mins.topics.length) {
    out.push("## Discussion", "");
    for (const t of mins.topics) out.push(`### ${t.title}`, "", ...t.notes.map((n) => `- ${n}`), "");
  }

  const turns = spokenTurns(m);
  if (turns.length) {
    out.push(`## What ${AGENT_NAME} said`, "");
    for (const t of turns) {
      const q = utterance(m, t.trigger);
      const a = utterance(m, t.utteranceId);
      if (q) out.push(`- ${clock(m.start, q.t)} ${speakerName(q.speaker)} asked: "${q.text}"`);
      if (a) out.push(`  ${AGENT_NAME}: "${a.text}"`);
      if (t.citations.length) out.push(`  Sources: ${t.citations.map((c) => `${c.source}${c.author ? ` (${c.author})` : ""}`).join("; ")}`);
    }
    out.push("");
  }

  out.push("## Attendees", "", ...m.attendees.map((id) => `- ${person(id).name}, ${person(id).role}${person(id).org ? `, ${person(id).org}` : ""}`), `- ${AGENT_NAME}, for ${OWNER.name}`, "");
  return out.join("\n");
}
