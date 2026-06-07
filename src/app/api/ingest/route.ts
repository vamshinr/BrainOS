import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";
import { z } from "zod";

export const runtime = "nodejs";
export const maxDuration = 300;

// Mnemosyne ingests raw text and synchronously extracts events + infers causal
// edges. The legacy {kind,title,url,model} fields are accepted but ignored —
// only the text and an optional source label matter.
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
    const res = await fetch(`${BACKEND_URL}/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: body.content,
        source_id: body.source_id ?? body.title ?? "ui",
      }),
    });
    if (!res.ok) {
      throw new Error(`Mnemosyne ${res.status}: ${await res.text()}`);
    }
    // { events_created, events_reinforced, edges_created, counts }
    return NextResponse.json(await res.json());
  } catch (e) {
    console.error("Ingest error:", e);
    return NextResponse.json({ error: "Ingest failed", detail: String(e) }, { status: 500 });
  }
}
