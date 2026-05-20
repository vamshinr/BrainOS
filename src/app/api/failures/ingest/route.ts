import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";
import { z } from "zod";
import { parseTrace, detectThrashing, synthesizeNarrative } from "@/lib/thrash-detector";

export const runtime = "nodejs";
export const maxDuration = 60;

const Body = z.object({
  transcript: z.string().min(1),
  repoLabel: z.string().optional(),
  model: z.string().optional(),
});

export async function POST(req: Request) {
  let body: z.infer<typeof Body>;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    return NextResponse.json({ error: "Invalid body", detail: String(e) }, { status: 400 });
  }

  const events = parseTrace(body.transcript);
  const episodes = detectThrashing(events);
  if (episodes.length === 0) {
    return NextResponse.json(
      { error: "No thrash episodes detected — nothing to ingest." },
      { status: 422 },
    );
  }

  const { title, content } = synthesizeNarrative(episodes, body.repoLabel);

  try {
    const res = await fetch(`${BACKEND_URL}/api/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind: "other",
        title,
        content,
        model: body.model,
      }),
    });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`Backend returned ${res.status}: ${errText}`);
    }
    const data = await res.json();
    return NextResponse.json({
      ...data,
      episodes,
      narrative: { title, content },
    });
  } catch (e) {
    console.error("Failure ingest error:", e);
    return NextResponse.json(
      { error: "Backend failed to enqueue", detail: String(e) },
      { status: 500 },
    );
  }
}
