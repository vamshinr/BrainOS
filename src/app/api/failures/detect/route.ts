import { NextResponse } from "next/server";
import { z } from "zod";
import { parseTrace, detectThrashing } from "@/lib/thrash-detector";

export const runtime = "nodejs";

const Body = z.object({
  transcript: z.string().min(1),
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
  return NextResponse.json({
    eventCount: events.length,
    episodes,
  });
}
