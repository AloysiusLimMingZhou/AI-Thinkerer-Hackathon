import { getMeeting } from "@/lib/data";
import { exportFilename, minutesMarkdown } from "@/lib/export";

/** GET /meetings/{id}/minutes, the minutes as Markdown. */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const meeting = getMeeting(id);
  if (!meeting || !meeting.minutes) {
    return new Response("There are no minutes for this meeting.", { status: 404 });
  }

  return new Response(minutesMarkdown(meeting), {
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Content-Disposition": `attachment; filename="${exportFilename(meeting, "minutes", "md")}"`,
    },
  });
}
