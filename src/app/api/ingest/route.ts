import { NextResponse } from "next/server";
import { z } from "zod";
import {
  extractFromSource,
  ingestSourceShape,
  mergeIntoState,
  reconcileUnit,
} from "@/lib/extractor";
import { mutate } from "@/lib/store";
import { hasGatewayCreds } from "@/lib/ai";

export const runtime = "nodejs";
export const maxDuration = 300;

const Body = z.object({
  kind: z.enum([
    "slack",
    "email",
    "ticket",
    "doc",
    "meeting",
    "wiki",
    "code",
    "other",
  ]),
  title: z.string().min(1),
  content: z.string().min(1),
  url: z.string().url().optional(),
});

export async function POST(req: Request) {
  if (!hasGatewayCreds()) {
    return NextResponse.json(
      {
        error:
          "No AI credentials. Set AI_GATEWAY_API_KEY (recommended), or OPENAI_API_KEY / ANTHROPIC_API_KEY.",
      },
      { status: 400 },
    );
  }

  let body: z.infer<typeof Body>;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    return NextResponse.json(
      { error: "Invalid body", detail: String(e) },
      { status: 400 },
    );
  }

  const source = ingestSourceShape(body);

  let extraction;
  try {
    extraction = await extractFromSource(source);
  } catch (e) {
    return NextResponse.json(
      { error: "Extraction failed", detail: String(e) },
      { status: 500 },
    );
  }

  const next = await mutate(async (state) => {
    const reconciliations = new Map<
      string,
      { supersedes: string[]; isDuplicate: boolean }
    >();
    for (const u of extraction.units) {
      try {
        const r = await reconcileUnit(u, state.units);
        reconciliations.set(u.id, r);
      } catch {
        reconciliations.set(u.id, { supersedes: [], isDuplicate: false });
      }
    }
    return mergeIntoState(
      state,
      source,
      extraction.entities,
      extraction.units,
      reconciliations,
    );
  });

  return NextResponse.json({
    sourceId: source.id,
    addedUnits: extraction.units.length,
    addedEntities: extraction.entities.length,
    totals: {
      sources: next.sources.length,
      entities: next.entities.length,
      units: next.units.length,
    },
  });
}
