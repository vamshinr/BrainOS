import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";
import { z } from "zod";

export const runtime = "nodejs";

const Body = z.object({
  winner_id: z.string().min(1),
  loser_id: z.string().min(1),
});

export async function POST(req: Request) {
  let body: z.infer<typeof Body>;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    return NextResponse.json({ error: "Invalid body", detail: String(e) }, { status: 400 });
  }

  try {
    const res = await fetch(`${BACKEND_URL}/api/conflicts/resolve`, {
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
      { error: "Failed to resolve conflict", detail: String(e) },
      { status: 500 },
    );
  }
}
