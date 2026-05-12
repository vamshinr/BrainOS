import { BACKEND_URL } from "@/lib/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 3600; // SSE connection can be long-lived

// Proxy the backend SSE stream straight through. We pass the upstream response
// body verbatim — Next.js doesn't transform ReadableStream<Uint8Array>, so the
// `data: ...\n\n` framing reaches the browser EventSource unchanged.
export async function GET(req: Request) {
  const upstream = await fetch(`${BACKEND_URL}/api/jobs/stream`, {
    headers: { accept: "text/event-stream" },
    // Forward the client's abort signal so closing the EventSource shuts the
    // upstream connection too instead of leaving zombie listeners on FastAPI.
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
