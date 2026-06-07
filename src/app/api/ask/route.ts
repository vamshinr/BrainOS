import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";
import { z } from "zod";

export const runtime = "nodejs";
export const maxDuration = 300;

// Maps the UI's question to Mnemosyne's causal (or associative) retrieval.
const Body = z.object({
  question: z.string().min(1),
  mode: z.enum(["causal", "associative"]).optional(),
  k: z.number().int().positive().max(50).optional(),
});

export async function POST(req: Request) {
  let body: z.infer<typeof Body>;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    return NextResponse.json({ error: "Invalid body", detail: String(e) }, { status: 400 });
  }

  try {
    const res = await fetch(`${BACKEND_URL}/retrieve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: body.question,
        mode: body.mode ?? "causal",
        k: body.k ?? 8,
      }),
    });
    if (!res.ok) {
      throw new Error(`Mnemosyne ${res.status}: ${await res.text()}`);
    }
    // causal: { anchor_event_id, chain, answer, excluded_distractors }
    // associative: { chunks }
    return NextResponse.json(await res.json());
  } catch (e) {
    console.error("Retrieve error:", e);
    return NextResponse.json({ error: "Retrieve failed", detail: String(e) }, { status: 500 });
  }
}
