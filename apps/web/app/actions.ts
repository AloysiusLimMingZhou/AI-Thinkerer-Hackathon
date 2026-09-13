"use server";

import { randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";
import { backend, BackendError, BackendUnreachable } from "@/lib/backend";
import { DEFAULT_AGENT, DEFAULT_OWNER, reasonText } from "@/lib/meeting";

/**
 * Every write to the backend goes through these Server Actions, so the operator token
 * stays on the server (docs/BACKEND_HANDOFF.md, "Frontend teammate: wire the demo").
 */

export type ActionState = { error?: string; ok?: string; sessionId?: string; answer?: string } | null;

function explain(e: unknown): string {
  if (e instanceof BackendUnreachable) return `${e.message} Start it with "uv run python main.py", or check ALLOY_BACKEND_URL.`;
  if (e instanceof BackendError) {
    if (e.status === 401) return "The backend rejected the token. Check BACKEND_API_TOKEN in apps/web/.env.local.";
    return e.message;
  }
  return "Something went wrong talking to the backend.";
}

/** Same rule as validate_meeting_url in the backend, checked before anything is created. */
function meetingUrlProblem(value: string): string | null {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return "That doesn't look like a link. Paste the full meeting URL.";
  }
  const supported = ["meet.google.com", "zoom.us", "teams.microsoft.com", "teams.live.com"];
  const hostOk = supported.some((h) => url.hostname === h || url.hostname.endsWith(`.${h}`));
  if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "443") || !hostOk) {
    return "Use a Google Meet, Zoom or Microsoft Teams link that starts with https://.";
  }
  if (!url.pathname || url.pathname === "/") return "That's the platform's home page. Paste the link to the meeting itself.";
  return null;
}

/** join_at must be timezone-aware, at least 10 minutes ahead and within 28 days. */
function joinAtProblem(iso: string): string | null {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "Pick a date and time to schedule.";
  const now = Date.now();
  if (t < now + 10 * 60_000) return "Schedule at least 10 minutes ahead, or choose Join now.";
  if (t > now + 28 * 86_400_000) return "Schedule within the next 28 days.";
  return null;
}

function field(form: FormData, name: string): string {
  return String(form.get(name) ?? "").trim();
}

export async function sendToMeeting(_prev: ActionState, form: FormData): Promise<ActionState> {
  const meetingUrl = field(form, "meeting_url");
  const title = field(form, "title") || "Meeting";
  const owner = field(form, "owner_name") || DEFAULT_OWNER;
  const agent = field(form, "agent_name") || DEFAULT_AGENT;
  const notes = field(form, "notes");
  const joinAt = field(form, "when") === "later" ? field(form, "join_at") : "";

  const urlProblem = meetingUrlProblem(meetingUrl);
  if (urlProblem) return { error: urlProblem };
  if (joinAt) {
    const p = joinAtProblem(joinAt);
    if (p) return { error: p };
  }
  if (form.get("consent") !== "yes") return { error: "Confirm that people in the meeting know Alloy will join and transcribe." };

  let sessionId: string;
  try {
    const session = await backend.createSession({ title, owner_name: owner, agent_name: agent, meeting_url: meetingUrl });
    sessionId = session.id;
    if (notes) await backend.addContext(sessionId, [{ source: "briefing", title: "Briefing notes", content: notes }]);
  } catch (e) {
    return { error: explain(e) };
  }

  try {
    await backend.launchBot(sessionId, { idempotency_key: randomUUID(), consent_confirmed: true, ...(joinAt ? { join_at: joinAt } : {}) });
  } catch (e) {
    revalidatePath("/");
    return { sessionId, error: `The meeting is saved, but ${agent} couldn't be sent yet. ${explain(e)}` };
  }
  revalidatePath("/");
  return { sessionId, ok: joinAt ? `${agent} is scheduled.` : `${agent} is on its way.` };
}

export async function launchBot(sessionId: string, _prev: ActionState, form: FormData): Promise<ActionState> {
  const joinAt = field(form, "when") === "later" ? field(form, "join_at") : "";
  if (joinAt) {
    const p = joinAtProblem(joinAt);
    if (p) return { error: p };
  }
  if (form.get("consent") !== "yes") return { error: "Confirm that people in the meeting know Alloy will join and transcribe." };
  try {
    await backend.launchBot(sessionId, { idempotency_key: randomUUID(), consent_confirmed: true, ...(joinAt ? { join_at: joinAt } : {}) });
  } catch (e) {
    if (e instanceof BackendError && e.status === 409) {
      return { error: "This meeting already had a launch. Start a new meeting to send the bot again." };
    }
    return { error: explain(e) };
  }
  revalidatePath(`/meetings/${sessionId}`);
  return { ok: "Sent." };
}

export async function leaveMeeting(sessionId: string, _prev: ActionState): Promise<ActionState> {
  try {
    await backend.leaveBot(sessionId);
  } catch (e) {
    if (e instanceof BackendError && e.status === 409) return { error: "The launch is still being confirmed. Try again in a moment." };
    return { error: explain(e) };
  }
  revalidatePath(`/meetings/${sessionId}`);
  return { ok: "Asked it to leave." };
}

export async function sayInMeeting(sessionId: string, _prev: ActionState, form: FormData): Promise<ActionState> {
  const text = field(form, "text");
  if (!text) return { error: "Type what it should say." };
  if (text.length > 5000) return { error: "Keep it under 5,000 characters." };
  try {
    await backend.say(sessionId, text);
  } catch (e) {
    if (e instanceof BackendError && e.status === 409) return { error: "It isn't in the call right now." };
    return { error: explain(e) };
  }
  revalidatePath(`/meetings/${sessionId}`);
  return { ok: "Queued. It plays as soon as the current audio finishes." };
}

export async function addNote(sessionId: string, _prev: ActionState, form: FormData): Promise<ActionState> {
  const title = field(form, "title") || "Note";
  const content = field(form, "content");
  if (!content) return { error: "Write the note first." };
  try {
    await backend.addContext(sessionId, [{ source: "briefing", title, content }]);
  } catch (e) {
    return { error: explain(e) };
  }
  revalidatePath(`/meetings/${sessionId}`);
  return { ok: "Saved. It can use this from the next question." };
}

export async function writeMinutes(sessionId: string, _prev: ActionState): Promise<ActionState> {
  try {
    await backend.generateMinutes(sessionId);
  } catch (e) {
    if (e instanceof BackendError && e.status === 409) return { error: "There's no transcript yet, so there's nothing to write up." };
    return { error: explain(e) };
  }
  revalidatePath(`/meetings/${sessionId}`);
  return { ok: "Minutes written." };
}

/** Rehearse without a call: post one caption to the speaking rules. */
export async function tryLine(sessionId: string, _prev: ActionState, form: FormData): Promise<ActionState> {
  const speaker = field(form, "speaker") || "Guest";
  const text = field(form, "text");
  const agent = field(form, "agent") || DEFAULT_AGENT;
  if (!text) return { error: "Type something someone might say." };
  try {
    const decision = await backend.utterance(sessionId, { speaker, text });
    revalidatePath(`/meetings/${sessionId}`);
    return decision.action === "answer"
      ? { ok: "It answered.", answer: decision.answer ?? "" }
      : { ok: `It stayed quiet. ${reasonText(decision.reason, agent)}` };
  } catch (e) {
    revalidatePath(`/meetings/${sessionId}`);
    return { error: explain(e) };
  }
}
