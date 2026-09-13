import "server-only";
import type { AgentDecision, BackendEvent, Bot, ContextNote, Health, Minutes, RecallStatus, Session, TranscriptEntry } from "./api-types";

/**
 * Server-side client for the Alloy backend, per docs/BACKEND_HANDOFF.md:
 * attaches the operator token, never caches, and keeps the backend's status codes.
 * The token is read from the server environment only and never reaches the browser.
 */

const BASE_URL = (process.env.ALLOY_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

export class BackendError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
    message: string,
  ) {
    super(message);
  }
}

/** The backend couldn't be reached at all (not running, wrong URL, tunnel down). */
export class BackendUnreachable extends Error {}

export function backendUrl(): string {
  return BASE_URL;
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const d = detail as { missing?: unknown };
    if (Array.isArray(d.missing)) return `Missing configuration: ${d.missing.join(", ")}`;
    if (Array.isArray(detail)) {
      // FastAPI validation errors: [{loc, msg}]
      return (detail as { msg?: string }[]).map((e) => e.msg).filter(Boolean).join("; ");
    }
  }
  return "The backend rejected the request.";
}

async function call<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const token = process.env.BACKEND_API_TOKEN;
  if (!token) {
    throw new BackendError(503, null, "BACKEND_API_TOKEN isn't set in apps/web/.env.local.");
  }
  const { json, headers, ...rest } = init;
  let response: Response;
  try {
    response = await fetch(BASE_URL + path, {
      ...rest,
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${token}`,
        ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new BackendUnreachable(`Can't reach the backend at ${BASE_URL}.`);
  }
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail;
    } catch {
      /* non-JSON error body */
    }
    throw new BackendError(response.status, detail, describe(detail));
  }
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? await response.json() : await response.arrayBuffer()) as T;
}

/** Returns null for a 404 instead of throwing. */
async function maybe<T>(path: string): Promise<T | null> {
  try {
    return await call<T>(path);
  } catch (e) {
    if (e instanceof BackendError && e.status === 404) return null;
    throw e;
  }
}

export const backend = {
  health: () => call<Health>("/health"),
  recallStatus: () => call<RecallStatus>("/recall/status"),

  listSessions: () => call<Session[]>("/sessions"),
  getSession: (id: string) => maybe<Session>(`/sessions/${encodeURIComponent(id)}`),
  createSession: (body: { title: string; owner_name: string; agent_name: string; meeting_url: string }) =>
    call<Session>("/sessions", { method: "POST", json: body }),

  addContext: (id: string, notes: { source: string; title: string; content: string }[]) =>
    call<ContextNote[]>(`/sessions/${encodeURIComponent(id)}/context`, { method: "POST", json: { notes } }),

  transcript: (id: string) => call<TranscriptEntry[]>(`/sessions/${encodeURIComponent(id)}/transcript`),
  events: (id: string, after = 0) => call<BackendEvent[]>(`/sessions/${encodeURIComponent(id)}/events?after=${after}`),

  minutes: (id: string) => maybe<Minutes>(`/sessions/${encodeURIComponent(id)}/minutes`),
  generateMinutes: (id: string) => call<Minutes>(`/sessions/${encodeURIComponent(id)}/minutes`, { method: "POST" }),

  bot: (id: string) => maybe<Bot>(`/sessions/${encodeURIComponent(id)}/bot`),
  launchBot: (id: string, body: { idempotency_key: string; consent_confirmed: true; join_at?: string }) =>
    call<Bot>(`/sessions/${encodeURIComponent(id)}/bot`, { method: "POST", json: body }),
  leaveBot: (id: string) => call<{ state: string }>(`/sessions/${encodeURIComponent(id)}/bot/leave`, { method: "POST" }),
  say: (id: string, text: string) =>
    call<{ id: string; state: string }>(`/sessions/${encodeURIComponent(id)}/bot/say`, { method: "POST", json: { text } }),

  /** Manual caption, for trying the speaking rules without a live call. */
  utterance: (id: string, body: { speaker: string; text: string }) =>
    call<AgentDecision>(`/sessions/${encodeURIComponent(id)}/utterances`, { method: "POST", json: body }),
};
