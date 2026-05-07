import { NextResponse } from "next/server";
import { z } from "zod";

export const runtime = "nodejs";
export const maxDuration = 300;

const Body = z.object({ question: z.string().min(1) });

export async function POST(req: Request) {
  let body: z.infer<typeof Body>;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    return NextResponse.json({ error: "Invalid body", detail: String(e) }, { status: 400 });
  }

  try {
    const backendRes = await fetch("http://localhost:8081/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: body.question }),
    });

    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }

    const data = await backendRes.json();

    return NextResponse.json({
      answer: data.answer,
      used: data.used ?? [],
      retrieved_texts: data.retrieved_texts ?? [],
      latency_ms: data.latency_ms ?? null,
      feedback: data.feedback ?? null,
    });
  } catch (e) {
    console.error("Agent Backend Error:", e);
    return NextResponse.json(
      { error: "Agent Backend failed", detail: String(e) },
      { status: 500 },
    );
  }
}
