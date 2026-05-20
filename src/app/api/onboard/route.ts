import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";
import { z } from "zod";

export const runtime = "nodejs";
export const maxDuration = 120;

const Body = z.object({
  department: z.string().default("general"),
  role: z.string().default(""),
});

export async function POST(req: Request) {
  let body: z.infer<typeof Body>;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    return NextResponse.json({ error: "Invalid body", detail: String(e) }, { status: 400 });
  }

  try {
    const res = await fetch(`${BACKEND_URL}/api/onboard`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`Backend ${res.status}: ${errText}`);
    }
    return NextResponse.json(await res.json());
  } catch (e) {
    return NextResponse.json(
      { error: "Failed to generate onboarding doc", detail: String(e) },
      { status: 500 },
    );
  }
}
