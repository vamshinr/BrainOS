import { NextResponse } from "next/server";
import { z } from "zod";

export const runtime = "nodejs";

const Body = z.object({
  channel_id: z.string().min(1),
  department: z.string().min(1),
});

export async function GET() {
  try {
    const backendRes = await fetch("http://localhost:8081/api/slack/channel_map", {
      cache: "no-store",
    });
    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }
    return NextResponse.json(await backendRes.json());
  } catch (e) {
    return NextResponse.json({ error: "Slack channel map failed", detail: String(e) }, { status: 500 });
  }
}

export async function POST(req: Request) {
  let body: z.infer<typeof Body>;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    return NextResponse.json({ error: "Invalid body", detail: String(e) }, { status: 400 });
  }

  try {
    const backendRes = await fetch("http://localhost:8081/api/slack/channel_map", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }
    return NextResponse.json(await backendRes.json());
  } catch (e) {
    return NextResponse.json({ error: "Slack channel map update failed", detail: String(e) }, { status: 500 });
  }
}

