import { backend, BackendError, BackendUnreachable } from "@/lib/backend";
import { exportFilename, isTranscriptFormat, renderTranscript, TRANSCRIPT_FORMATS } from "@/lib/export";
import { answersFrom, mergedTranscript } from "@/lib/meeting";

/** GET /meetings/{id}/transcript?format=txt|md|json, proxied from the backend. */
export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const format = new URL(request.url).searchParams.get("format") ?? "txt";
  if (!isTranscriptFormat(format)) {
    return new Response(`Unknown format "${format}". Use one of: ${Object.keys(TRANSCRIPT_FORMATS).join(", ")}.`, { status: 400 });
  }
  try {
    const session = await backend.getSession(id);
    if (!session) return new Response("Meeting not found.", { status: 404 });
    const [transcript, events] = await Promise.all([backend.transcript(id), backend.events(id)]);
    const lines = mergedTranscript(transcript, answersFrom(events), session.agent_name);
    const { mime, ext } = TRANSCRIPT_FORMATS[format];
    return new Response(renderTranscript(session, lines, format), {
      headers: {
        "Content-Type": mime,
        "Content-Disposition": `attachment; filename="${exportFilename(session, "transcript", ext)}"`,
        "Cache-Control": "no-store",
      },
    });
  } catch (e) {
    if (e instanceof BackendUnreachable) return new Response(e.message, { status: 502 });
    if (e instanceof BackendError) return new Response(e.message, { status: e.status });
    throw e;
  }
}
