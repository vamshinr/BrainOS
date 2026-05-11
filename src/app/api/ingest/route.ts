import { NextResponse } from "next/server";
import { z } from "zod";
import { invalidateCache } from "@/lib/store";

export const runtime = "nodejs";
export const maxDuration = 300;

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
    const backendRes = await fetch(`${BACKEND_URL}/api/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }

    const data = await backendRes.json();

    // Invalidate the Next.js in-memory cache so the dashboard reads fresh data
    // from the brain.json that Python just wrote to.
    invalidateCache();

    const totals = data.brain_totals ?? { sources: 1, entities: 0, units: data.units_stored ?? 0 };

    return NextResponse.json({
      sourceId: data.source_id,
      addedUnits: data.units_stored ?? 0,
      addedEntities: data.entities_stored ?? 0,
      addedRelationships: data.relationships_stored ?? 0,
      supersededUnits: data.units_superseded ?? 0,
      totals,
    });
  } catch (e) {
    console.error("Agent Backend Error:", e);
    return NextResponse.json({ error: "Agent Backend failed", detail: String(e) }, { status: 500 });
  }
}
