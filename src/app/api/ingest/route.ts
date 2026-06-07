import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";
import { z } from "zod";

export const runtime = "nodejs";

// Enqueue an async ingestion job. Returns immediately with { job_id }; progress
// is streamed to the QueueDock. The legacy {kind,url,model} fields are accepted
// but ignored — only the text and an optional source label matter.
const Body = z.object({
  content: z.string().min(1),
  title: z.string().optional(),
  source_id: z.string().optional(),
  kind: z.string().optional(),
  url: z.string().optional(),
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
    const res = await fetch(`${BACKEND_URL}/api/jobs/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: body.content,
        source_id: body.source_id ?? body.title ?? "ui",
        title: body.title ?? "",
        kind: "ingest_text",
      }),
    });
    if (!res.ok) throw new Error(`Mnemosyne ${res.status}: ${await res.text()}`);
    return NextResponse.json(await res.json()); // { job_id }
  } catch (e) {
    console.error("Enqueue error:", e);
    return NextResponse.json({ error: "Enqueue failed", detail: String(e) }, { status: 500 });
  }
}
