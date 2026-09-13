import { getMeeting } from "@/lib/data";
import { exportFilename, isTranscriptFormat, renderTranscript, TRANSCRIPT_FORMATS } from "@/lib/export";

/** GET /meetings/{id}/transcript?format=txt|md|vtt|json */
export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const meeting = getMeeting(id);
  if (!meeting || meeting.status !== "attended") {
    return new Response("There’s no transcript for this meeting.", { status: 404 });
  }

  const format = new URL(request.url).searchParams.get("format") ?? "txt";
  if (!isTranscriptFormat(format)) {
    return new Response(`Unknown format "${format}". Use one of: ${Object.keys(TRANSCRIPT_FORMATS).join(", ")}.`, { status: 400 });
  }

  const { mime, ext } = TRANSCRIPT_FORMATS[format];
  return new Response(renderTranscript(meeting, format), {
    headers: {
      "Content-Type": mime,
      "Content-Disposition": `attachment; filename="${exportFilename(meeting, "transcript", ext)}"`,
    },
  });
}
