import { NextResponse } from "next/server";
import { z } from "zod";
import {
  extractFromSource,
  ingestSourceShape,
  mergeIntoState,
  reconcileUnit,
} from "@/lib/extractor";
import { mutate } from "@/lib/store";
import { hasGatewayCreds } from "@/lib/ai";

export const runtime = "nodejs";
export const maxDuration = 300;

const Body = z.object({
  kind: z.enum([
    "slack",
    "email",
    "ticket",
    "doc",
    "meeting",
    "wiki",
    "code",
    "other",
  ]),
  title: z.string().min(1),
  content: z.string().min(1),
  url: z.string().url().optional(),
});

export async function POST(req: Request) {
  let body: z.infer<typeof Body>;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    return NextResponse.json(
      { error: "Invalid body", detail: String(e) },
      { status: 400 },
    );
  }

  try {
    // Forward the request to the Python Multi-Agent Backend
    const backendRes = await fetch("http://localhost:8081/api/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });

    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }

    const data = await backendRes.json();

    // Return what the Next.js frontend expects
    return NextResponse.json({
      sourceId: data.structuring?.id || "mock-id",
      addedUnits: data.structuring?.graph_nodes_updated || 1,
      addedEntities: 0,
      totals: {
        sources: 1,
        entities: 0,
        units: data.structuring?.graph_nodes_updated || 1,
      },
    });
  } catch (e) {
    console.error("Agent Backend Error:", e);
    return NextResponse.json({ error: "Agent Backend failed", detail: String(e) }, { status: 500 });
  }
}
