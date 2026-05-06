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
  if (!hasGatewayCreds()) {
    return NextResponse.json(
      { error: "No AI credentials configured." },
      { status: 400 },
    );
  }

  let body;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    return NextResponse.json({ error: "Invalid body", detail: String(e) }, { status: 400 });
  }

  const state = await readState();
  const fresh = state.units.filter((u) => !u.stale && !u.supersededBy);
  const ranked = fresh
    .map((u) => ({ u, s: score(u, body.question) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s)
    .slice(0, 30)
    .map((x) => x.u);

  // if nothing matched, give the model the top items by recency anyway
  const context = ranked.length > 0 ? ranked : fresh.slice(0, 30);

  const contextBlock = context
    .map(
      (u) =>
        `[${u.id}] (${u.kind}, conf=${u.confidence.toFixed(2)}) ${u.statement}`,
    )
    .join("\n");

  const { text } = await generateText({
    model: model(),
    system: `You answer questions using ONLY the company knowledge units provided. Each unit has an ID in [brackets].
Rules:
- Cite the IDs you used in square brackets at the end of relevant sentences, e.g. "[abc123]".
- If the knowledge units do not contain the answer, say so plainly. Do not guess.
- Be terse. Two or three sentences is usually enough.
- If multiple units conflict, prefer the higher-confidence one and note the conflict.`,
    prompt: `KNOWLEDGE UNITS:
${contextBlock || "(none)"}

QUESTION: ${body.question}`,
  });

  return NextResponse.json({ answer: text, used: context.map((u) => u.id) });
}
