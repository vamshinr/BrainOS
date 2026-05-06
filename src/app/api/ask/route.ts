import { NextResponse } from "next/server";
import { generateText } from "ai";
import { z } from "zod";
import { readState } from "@/lib/store";
import { hasGatewayCreds, model } from "@/lib/ai";
import type { KnowledgeUnit } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 300;

const Body = z.object({ question: z.string().min(1) });

function score(unit: KnowledgeUnit, query: string): number {
  const q = query.toLowerCase();
  const tokens = q.split(/\W+/).filter((t) => t.length > 2);
  if (tokens.length === 0) return 0;
  const hay = (
    unit.statement +
    " " +
    unit.subject +
    " " +
    unit.entities.join(" ")
  ).toLowerCase();
  let s = 0;
  for (const t of tokens) {
    if (hay.includes(t)) s += 1;
  }
  return s * (unit.confidence || 0.5);
}

export async function POST(req: Request) {
  let body;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    return NextResponse.json({ error: "Invalid body", detail: String(e) }, { status: 400 });
  }

  try {
    // Forward the request to the Python Multi-Agent Backend
    const backendRes = await fetch("http://localhost:8081/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: body.question })
    });

    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }

    const data = await backendRes.json();

    // Return what the Next.js frontend expects
    return NextResponse.json({
      answer: data.answer,
      used: [] // We can populate this later when we integrate ChromaDB citations
    });
  } catch (e) {
    console.error("Agent Backend Error:", e);
    return NextResponse.json({ error: "Agent Backend failed", detail: String(e) }, { status: 500 });
  }
}
