import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";
import { z } from "zod";

export const runtime = "nodejs";
export const maxDuration = 60;

const Body = z.object({
  kind: z.enum(["slack", "email", "ticket", "doc", "meeting", "wiki", "code", "other"]),
  title: z.string().min(1).optional(),
  content: z.string().min(1),
  url: z.string().url().optional(),
  model: z.string().optional(),
});

export async function POST(req: Request) {
  let body: z.infer<typeof Body>;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    return NextResponse.json({ error: "Invalid body", detail: String(e) }, { status: 400 });
  }

  try {
    const backendRes = await fetch(`${BACKEND_URL}/api/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }

    // Pass the enqueue response through verbatim — {job_id, status,
    // queue_position, title}. The actual ingest happens asynchronously on the
    // backend worker; the QueueDock subscribes to /api/jobs/stream for
    // progress and triggers cache invalidation when the job finishes.
    const data = await backendRes.json();
    return NextResponse.json(data, { status: backendRes.status });
  } catch (e) {
    console.error("Ingest enqueue error:", e);
    return NextResponse.json({ error: "Backend failed to enqueue", detail: String(e) }, { status: 500 });
  }
}
