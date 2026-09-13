import { backend, BackendError, BackendUnreachable } from "@/lib/backend";
import { exportFilename, minutesFile } from "@/lib/export";

/** GET /meetings/{id}/minutes, the backend's minutes as a Markdown download. */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  try {
    const [session, minutes] = await Promise.all([backend.getSession(id), backend.minutes(id)]);
    if (!session) return new Response("Meeting not found.", { status: 404 });
    if (!minutes) return new Response("There are no minutes for this meeting yet.", { status: 404 });
    return new Response(minutesFile(session, minutes), {
      headers: {
        "Content-Type": "text/markdown; charset=utf-8",
        "Content-Disposition": `attachment; filename="${exportFilename(session, "minutes", "md")}"`,
        "Cache-Control": "no-store",
      },
    });
  } catch (e) {
    if (e instanceof BackendUnreachable) return new Response(e.message, { status: 502 });
    if (e instanceof BackendError) return new Response(e.message, { status: e.status });
    throw e;
  }
}
