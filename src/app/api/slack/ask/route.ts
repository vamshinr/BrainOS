import { NextResponse } from "next/server";
import { z } from "zod";

export const runtime = "nodejs";
export const maxDuration = 300;

const Body = z.object({
  channel_id: z.string().min(1),
  question: z.string().min(1),
  department: z.string().optional(),
  send_to_slack: z.boolean().optional(),
  thread_ts: z.string().optional(),
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
    const backendRes = await fetch(`${BACKEND_URL}/api/slack/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, send_to_slack: body.send_to_slack ?? false }),
    });
    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }
    return NextResponse.json(await backendRes.json());
  } catch (e) {
    console.error("Slack ask failed:", e);
    return NextResponse.json({ error: "Slack ask failed", detail: String(e) }, { status: 500 });
  }
}

