import { NextResponse } from "next/server";
import { z } from "zod";
import { invalidateCache } from "@/lib/store";

export const runtime = "nodejs";
export const maxDuration = 300;

const Body = z.object({
  query: z.string().min(1),
  channel_id: z.string().optional(),
  channel_name: z.string().optional(),
  department: z.string().optional(),
  limit: z.number().int().min(1).max(100).optional(),
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
    const backendRes = await fetch(`${BACKEND_URL}/api/slack/search_ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }
    const data = await backendRes.json();
    invalidateCache();
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json({ error: "Slack search ingest failed", detail: String(e) }, { status: 500 });
  }
}
