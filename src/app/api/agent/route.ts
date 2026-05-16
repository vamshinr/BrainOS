import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";
import { z } from "zod";

export const runtime = "nodejs";
export const maxDuration = 300;

const Body = z.object({
  session_id: z.string().optional(),
  message: z.string().min(1),
});

export async function POST(req: Request) {
  let body: z.infer<typeof Body>;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    return NextResponse.json({ error: "Invalid body", detail: String(e) }, { status: 400 });
  }

  try {
    const backendRes = await fetch(`${BACKEND_URL}/api/agent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: body.session_id, message: body.message }),
    });

    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }

    const data = await backendRes.json();
    return NextResponse.json(data);
  } catch (e) {
    console.error("[Agent API] Error:", e);
    return NextResponse.json(
      { error: "Agent backend failed", detail: String(e) },
      { status: 500 }
    );
  }
}
