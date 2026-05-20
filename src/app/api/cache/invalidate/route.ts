import { NextResponse } from "next/server";
import { invalidateCache } from "@/lib/store";

export const runtime = "nodejs";

// Called by the QueueDock when a job finishes so the next render of /, /graph,
// /skills, etc. re-reads fresh brain state. We can't do this inside the ingest
// proxies anymore — those return before the actual work is done.
export async function POST() {
  invalidateCache();
  return NextResponse.json({ ok: true });
}
