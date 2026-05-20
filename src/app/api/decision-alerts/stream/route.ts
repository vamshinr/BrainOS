import { BACKEND_URL } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 3600;

export async function GET(req: Request) {
  const upstream = await fetch(`${BACKEND_URL}/api/decision-alerts/stream`, {
    headers: { accept: "text/event-stream" },
    signal: req.signal,
    cache: "no-store",
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(`upstream error: ${upstream.status}`, {
      status: upstream.status || 502,
    });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
      Connection: "keep-alive",
    },
  });
}
