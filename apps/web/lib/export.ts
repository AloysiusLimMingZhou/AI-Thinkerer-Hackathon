import type { Minutes, Session } from "./api-types";
import { clock, dayKey, longDay } from "./format";
import type { Line } from "./meeting";

/**
 * Transcript and minutes downloads, built from GET /sessions/{id}/transcript plus the
 * delegate's answers from the event log (the backend's transcript leaves them out).
 */

export const TRANSCRIPT_FORMATS = {
  txt: { label: "Plain text", ext: "txt", mime: "text/plain; charset=utf-8" },
  md: { label: "Markdown", ext: "md", mime: "text/markdown; charset=utf-8" },
  json: { label: "JSON", ext: "json", mime: "application/json; charset=utf-8" },
} as const;

export type TranscriptFormat = keyof typeof TRANSCRIPT_FORMATS;

export function isTranscriptFormat(f: string | null): f is TranscriptFormat {
  return f !== null && f in TRANSCRIPT_FORMATS;
}

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "").slice(0, 60) || "meeting";
}

export function exportFilename(session: Session, kind: "transcript" | "minutes", ext: string): string {
  return `${dayKey(session.created_at)}-${slug(session.title)}-${kind}.${ext}`;
}

function heading(session: Session): string {
  return `${session.title}, ${longDay(session.created_at)}`;
}

const NOTE = (agent: string) => `Captions by Recall. Lines marked "${agent} (answer)" come from ${agent}'s answer log.`;

function who(l: Line, agent: string): string {
  return l.agent ? `${agent} (answer)` : l.speaker;
}

export function renderTranscript(session: Session, lines: Line[], format: TranscriptFormat): string {
  const agent = session.agent_name;
  switch (format) {
    case "txt":
      return [heading(session), NOTE(agent), "", ...lines.map((l) => `[${clock(l.at, true)}] ${who(l, agent)}: ${l.text}`), ""].join("\n");
    case "md": {
      const out = [`# ${session.title}`, "", `${longDay(session.created_at)}. ${NOTE(agent)}`, ""];
      let prev = "";
      for (const l of lines) {
        const name = who(l, agent);
        if (name !== prev) out.push(`**${name}**, ${clock(l.at, true)}  `);
        out.push(l.agent ? `> ${l.text}` : l.text, "");
        prev = name;
      }
      return out.join("\n");
    }
    case "json":
      return JSON.stringify(
        {
          session: { id: session.id, title: session.title, meeting_url: session.meeting_url, created_at: session.created_at, agent_name: agent },
          lines: lines.map((l) => ({ at: l.at, speaker: l.agent ? agent : l.speaker, text: l.text, from: l.agent ? "answer_log" : "transcript" })),
        },
        null,
        2,
      );
  }
}

export function minutesFile(session: Session, minutes: Minutes): string {
  return minutes.content.trimStart().startsWith("#") ? minutes.content : `# ${heading(session)}: minutes\n\n${minutes.content}`;
}
